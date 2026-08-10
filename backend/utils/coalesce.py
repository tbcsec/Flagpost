"""Per-key leading + trailing coalescer for fan-out (#175).

A burst of same-key events (mass solves at the start/end of a competition, a
cascade of dynamic re-values) fans out one broadcast per event, and each
broadcast makes every connected client refetch. This collapses a burst per
key: the first hit fires immediately (leading edge, so a lone event has no
added latency), further hits inside ``window`` seconds coalesce into a single
trailing fire when the window closes — which reopens it, so a steady stream
fires at most once per window per key and the last value is never lost.

This mirrors the client's activity throttle (``frontend/src/lib/live.ts``), but
on the server, so the *fan-out itself* is throttled rather than only each
client's refetch. Steady, well-spaced events (each older than ``window``) each
fire on their own leading edge — coalescing only bites under a burst, which is
exactly when the refetch storm is worst.

The window is scheduled with ``loop.call_later`` (a timer handle, silently
dropped at loop close) rather than a sleeping task, so it leaves no pending
``asyncio.Task`` behind a short-lived test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

Send = Callable[[Hashable, Any], Awaitable[None]]


class Coalescer:
    def __init__(self, window: float, send: Send) -> None:
        self._window = window
        self._send = send
        self._open: set[Hashable] = set()
        self._pending: dict[Hashable, Any] = {}
        # Strong refs to in-flight trailing sends so they aren't GC'd mid-flight.
        self._tasks: set[asyncio.Task] = set()

    async def hit(self, key: Hashable, value: Any = None) -> None:
        """Register an event for ``key``. Awaits the leading-edge send inline so
        two different keys emitted in order (e.g. attempted then solved) reach a
        socket in that order; the trailing send is off the caller's path."""
        if key in self._open:
            self._pending[key] = value  # latest wins; fired when the window closes
            return
        self._open.add(key)
        await self._send(key, value)
        self._arm(key)

    def _arm(self, key: Hashable) -> None:
        asyncio.get_running_loop().call_later(self._window, self._on_close, key)

    def _on_close(self, key: Hashable) -> None:
        if key in self._pending:
            value = self._pending.pop(key)
            self._spawn(self._send(key, value))  # trailing edge
            self._arm(key)  # reopen — a stream keeps firing once per window
        else:
            self._open.discard(key)

    def _spawn(self, coro: Awaitable[None]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
