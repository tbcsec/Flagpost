"""In-process async pub/sub event bus (ARCHITECTURE.md §3, ADR-0005).

Core code emits named ``<entity>.<verb>`` events (§3.2) and never needs to
know who is listening; consumers — the audit log today, automations and
notifications later — subscribe independently. Design commitments from §3.1
and their costs from ADR-0005:

- **Wildcard subscriptions.** ``challenge.*`` (or ``*``) matches by segment.
- **Two dispatch lanes (ADR-0012).** A subscription runs either **foreground**
  (the default — awaited together, so the triggering request only returns once
  they finish; keeps the audit log durable and "emit-then-assert" tests
  deterministic) or **background** (``background=True`` — scheduled
  fire-and-forget so a slow/external handler like an outbound webhook never
  holds up the response, honouring §3.1's non-blocking property for the
  handlers that need it). A background handler's work isn't guaranteed done
  when ``emit`` returns and is lost on a mid-dispatch crash — best-effort by
  design; ``wait_for_background()`` lets tests await it rather than race.
- **Isolated failure + per-handler timeout.** A handler that raises or hangs
  is logged and dropped, never allowed to break sibling handlers, in either
  lane. The timeout addresses ADR-0005's flagged risk of a hung handler (e.g. a
  webhook) that would otherwise never complete.
- **Per-owner ownership.** Handlers may be tagged with an owner id so a
  plugin's handlers can be detached wholesale when it's disabled (§3.1). No
  plugin consumes this yet; the hook exists so the bus doesn't need reworking
  when the module loader arrives.

This is a single-process bus — it does not survive a restart or fan out across
backend instances (ADR-0005). Acceptable for the Docker Compose deployment
model; revisit before horizontal scaling.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from utils import metrics

logger = logging.getLogger("event_bus")

EventPayload = dict[str, Any]
Handler = Callable[[str, EventPayload], Awaitable[None]]

DEFAULT_HANDLER_TIMEOUT = 10.0  # seconds


@dataclass
class _Subscription:
    pattern: str
    handler: Handler
    owner: str | None = None
    # Foreground (default) handlers are awaited by emit(); background handlers
    # are scheduled fire-and-forget so a slow one doesn't block the request
    # (ADR-0012).
    background: bool = False
    _segments: list[str] = field(init=False)

    def __post_init__(self) -> None:
        self._segments = self.pattern.split(".")

    def matches(self, event_name: str) -> bool:
        name_segments = event_name.split(".")
        # A bare "*" matches everything.
        if self.pattern == "*":
            return True
        if len(self._segments) != len(name_segments):
            return False
        return all(
            pat == "*" or pat == seg
            for pat, seg in zip(self._segments, name_segments)
        )


class EventBus:
    def __init__(self, handler_timeout: float = DEFAULT_HANDLER_TIMEOUT) -> None:
        self._subscriptions: list[_Subscription] = []
        self._handler_timeout = handler_timeout
        # Strong refs to in-flight background tasks so they aren't garbage
        # collected mid-run (asyncio only holds a weak ref); each removes itself
        # on completion. wait_for_background() drains this for tests.
        self._background_tasks: set[asyncio.Task] = set()

    def on(
        self, pattern: str, *, owner: str | None = None, background: bool = False
    ) -> Callable[[Handler], Handler]:
        """Decorator registering ``handler`` for events matching ``pattern``.

        ``pattern`` is a ``<entity>.<verb>`` name where any segment may be
        ``*`` (e.g. ``challenge.*``), or the bare ``*`` to catch everything.
        ``background=True`` opts the handler into fire-and-forget dispatch
        (ADR-0012) — for slow/external work that must not block the request.
        """

        def decorator(handler: Handler) -> Handler:
            self.subscribe(pattern, handler, owner=owner, background=background)
            return handler

        return decorator

    def subscribe(
        self,
        pattern: str,
        handler: Handler,
        *,
        owner: str | None = None,
        background: bool = False,
    ) -> None:
        self._subscriptions.append(
            _Subscription(pattern, handler, owner, background)
        )

    def unsubscribe_owner(self, owner: str) -> None:
        """Detach every handler registered by ``owner`` (e.g. a disabled plugin)."""
        self._subscriptions = [
            s for s in self._subscriptions if s.owner != owner
        ]

    async def emit(self, event_name: str, payload: EventPayload) -> None:
        """Dispatch ``event_name`` to all matching handlers (ADR-0012).

        Foreground handlers are awaited together before this returns (so the
        mutation's request sees them complete — audit durability, deterministic
        tests). Background handlers are scheduled fire-and-forget and *not*
        awaited, so a slow one never holds up the caller. Individual handler
        failures/timeouts are isolated and logged in either lane, never
        re-raised into the caller — a mutation's success never depends on its
        listeners.
        """
        matching = [s for s in self._subscriptions if s.matches(event_name)]
        if not matching:
            metrics.record_event(event_name, 0.0)
            return
        for sub in matching:
            if sub.background:
                task = asyncio.ensure_future(self._run(sub, event_name, payload))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
        foreground = [s for s in matching if not s.background]
        # Time only the foreground lane (background is fire-and-forget, ADR-0012):
        # start the clock after scheduling the background tasks. A no-op until
        # metrics are enabled; counts every emit regardless.
        start = time.perf_counter()
        if foreground:
            await asyncio.gather(
                *(self._run(s, event_name, payload) for s in foreground)
            )
        metrics.record_event(event_name, time.perf_counter() - start)

    async def wait_for_background(self) -> None:
        """Await every currently-scheduled background handler.

        Test-only helper: background dispatch is fire-and-forget (ADR-0012), so
        a test that asserts on a background handler's effect awaits this first
        rather than sleeping and racing. (Production never calls this — there,
        background handlers run detached, already bounded by the per-handler
        timeout in ``_run``.)

        **Bounded so a straggler can never hang the whole suite.** The per-test
        conftest teardown drains here before ``drop_all``; intermittently a
        background task scheduled during the test was still pending at teardown
        and sat *un-driven* (e.g. its ``_run`` timeout timer belongs to the
        test's event loop, which the fixture-finaliser loop no longer runs), so
        a plain ``gather`` awaited it forever — a silent multi-minute CI hang
        that only surfaced under 2-core contention. Each batch now waits at most
        the per-handler timeout plus a small slack; a task that hasn't settled by
        then is cancelled and dropped from tracking, so the drain always
        terminates. The common case — handlers finishing in milliseconds — is
        unchanged.
        """
        while self._background_tasks:
            batch = tuple(self._background_tasks)
            # ``asyncio.wait`` (unlike ``gather``/``wait_for``) returns after the
            # timeout WITHOUT awaiting the tasks or their cancellation, so it can
            # never itself hang on a task that won't settle — the key property
            # ``wait_for`` lacks (it awaits the cancellation it requests).
            _done, pending = await asyncio.wait(
                batch, timeout=self._handler_timeout + 2
            )
            if pending:
                logger.error(
                    "wait_for_background: %d task(s) did not settle; cancelling",
                    len(pending),
                )
                for task in pending:
                    task.cancel()
            # Stop tracking this batch no matter what — a cancelled straggler
            # finishes out of band and must not re-wedge the drain. New tasks
            # scheduled meanwhile stay in the set and the loop drains them.
            self._background_tasks.difference_update(batch)

    async def _run(
        self, sub: _Subscription, event_name: str, payload: EventPayload
    ) -> None:
        try:
            await asyncio.wait_for(
                sub.handler(event_name, payload), timeout=self._handler_timeout
            )
        except asyncio.TimeoutError:
            logger.error(
                "event handler timed out after %ss: pattern=%s event=%s",
                self._handler_timeout,
                sub.pattern,
                event_name,
            )
        except Exception:  # noqa: BLE001 - isolation is the whole point
            logger.exception(
                "event handler failed: pattern=%s event=%s",
                sub.pattern,
                event_name,
            )


# Module-level singleton the whole backend shares (§3.1).
event_bus = EventBus()
