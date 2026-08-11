"""Per-key leading + trailing coalescer for fan-out (#175).

A burst of same-key events (mass solves at the start/end of a competition, a
cascade of dynamic re-values) fans out one broadcast per event, and each
broadcast makes every connected client refetch/patch. This collapses a burst
per key: the first hit fires immediately (leading edge, so a lone event has no
added latency), further hits inside ``window`` seconds coalesce into a single
trailing fire when the window closes — which reopens it, so a steady stream
fires at most once per window per key and the last value is never lost.

This mirrors the client's activity throttle (``frontend/src/lib/live.ts``), but
on the server, so the *fan-out itself* is throttled rather than only each
client's refetch. Steady, well-spaced events (each older than ``window``) each
fire on their own leading edge — coalescing only bites under a burst, which is
exactly when the storm is worst.

``send`` returns whether it actually delivered (e.g. False when the room is
empty). A key is only *tracked* (and a trailing armed) once a send has really
reached someone: events that occur while nobody is watching are dropped rather
than buffered into a phantom trailing ping delivered to whoever connects next
(who refetches fresh on connect anyway). This also keeps the coalescer from
leaking timers for rooms that emptied.

Windows are scheduled with ``loop.call_later`` (a timer handle, cancelled on
fire so it can't accumulate) rather than a sleeping task, so nothing pending is
left behind a short-lived test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

# send(key, value) -> delivered?  (False means "nobody received it")
Send = Callable[[Hashable, Any], Awaitable[bool]]

_MISSING = object()

# Live instances, so tests can reset all coalescer state between cases.
_INSTANCES: list["Coalescer"] = []


def reset_all_coalescers() -> None:
    """Cancel pending windows and clear state on every coalescer — test hook,
    so a trailing timer armed in one test can't fire during the next."""
    for c in _INSTANCES:
        c.reset()


class Coalescer:
    def __init__(self, window: float, send: Send) -> None:
        self._window = window
        self._send = send
        self._open: set[Hashable] = set()
        self._pending: dict[Hashable, Any] = {}
        self._timers: set[asyncio.TimerHandle] = set()
        # Strong refs to in-flight trailing sends so they aren't GC'd mid-flight.
        self._tasks: set[asyncio.Task] = set()
        _INSTANCES.append(self)

    async def hit(self, key: Hashable, value: Any = None) -> None:
        """Register an event for ``key``. Awaits the leading-edge send inline so
        two different keys emitted in order (e.g. attempted then solved) reach a
        socket in that order; the trailing send is off the caller's path. The key
        is only tracked once a send actually delivers, so bursts that happen with
        nobody watching don't buffer a trailing ping for the next connector."""
        if key in self._open:
            self._pending[key] = value  # latest wins; fired when the window closes
            return
        if await self._send(key, value):
            self._open.add(key)
            self._arm(key)

    def _arm(self, key: Hashable) -> None:
        loop = asyncio.get_running_loop()

        def fire() -> None:
            self._timers.discard(handle)  # cancelled-on-fire → no accumulation
            self._spawn(self._close(key))

        handle = loop.call_later(self._window, fire)
        self._timers.add(handle)

    async def _close(self, key: Hashable) -> None:
        value = self._pending.pop(key, _MISSING)
        if value is _MISSING:
            self._open.discard(key)  # window closed quiet → stop tracking
            return
        if await self._send(key, value):  # trailing edge
            self._arm(key)  # keep firing at most once per window under a stream
        else:
            self._open.discard(key)

    def _spawn(self, coro: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def reset(self) -> None:
        for handle in self._timers:
            handle.cancel()
        self._timers.clear()
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        self._open.clear()
        self._pending.clear()
