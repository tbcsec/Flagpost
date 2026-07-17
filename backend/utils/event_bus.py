"""In-process async pub/sub event bus (ARCHITECTURE.md §3, ADR-0005).

Core code emits named ``<entity>.<verb>`` events (§3.2) and never needs to
know who is listening; consumers — the audit log today, automations and
notifications later — subscribe independently. Design commitments from §3.1
and their costs from ADR-0005:

- **Wildcard subscriptions.** ``challenge.*`` (or ``*``) matches by segment.
- **Non-blocking emit.** Handlers are dispatched onto the event loop and
  awaited as a group; ``emit`` itself returns as soon as they're scheduled so
  a slow handler never holds up the request that triggered the event.
- **Isolated failure + per-handler timeout.** A handler that raises or hangs
  is logged and dropped, never allowed to break sibling handlers. The timeout
  addresses ADR-0005's flagged risk of a hung handler (e.g. a webhook) that
  would otherwise never complete.
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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("event_bus")

EventPayload = dict[str, Any]
Handler = Callable[[str, EventPayload], Awaitable[None]]

DEFAULT_HANDLER_TIMEOUT = 10.0  # seconds


@dataclass
class _Subscription:
    pattern: str
    handler: Handler
    owner: str | None = None
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

    def on(
        self, pattern: str, *, owner: str | None = None
    ) -> Callable[[Handler], Handler]:
        """Decorator registering ``handler`` for events matching ``pattern``.

        ``pattern`` is a ``<entity>.<verb>`` name where any segment may be
        ``*`` (e.g. ``challenge.*``), or the bare ``*`` to catch everything.
        """

        def decorator(handler: Handler) -> Handler:
            self.subscribe(pattern, handler, owner=owner)
            return handler

        return decorator

    def subscribe(
        self, pattern: str, handler: Handler, *, owner: str | None = None
    ) -> None:
        self._subscriptions.append(_Subscription(pattern, handler, owner))

    def unsubscribe_owner(self, owner: str) -> None:
        """Detach every handler registered by ``owner`` (e.g. a disabled plugin)."""
        self._subscriptions = [
            s for s in self._subscriptions if s.owner != owner
        ]

    async def emit(self, event_name: str, payload: EventPayload) -> None:
        """Dispatch ``event_name`` to all matching handlers concurrently.

        Returns once handlers are scheduled and gathered; individual handler
        failures/timeouts are isolated and logged, never re-raised into the
        caller, so a mutation's success never depends on its listeners.
        """
        matching = [s for s in self._subscriptions if s.matches(event_name)]
        if not matching:
            return
        await asyncio.gather(
            *(self._run(s, event_name, payload) for s in matching)
        )

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
