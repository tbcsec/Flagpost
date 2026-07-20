"""Rate-limiter interface (ARCHITECTURE.md §13.2).

Flag submission is the one endpoint a competitor has direct incentive to
script, so it gets a tighter, dedicated limit than general API traffic. That
limit sits behind this abstraction for the same reason object storage does
(§13.3): production uses Redis (shared across workers, survives a reload),
while the test suite swaps in an in-memory double and stays infra-free
(ADR-0006). Callers never touch a Redis client directly.

The limiter is a **sliding window**: at most ``limit`` hits are allowed for a
key in any trailing ``window_seconds``. ``hit`` records an attempt and reports
whether it is within the limit.
"""

from __future__ import annotations

from typing import Protocol


class RateLimiter(Protocol):
    async def hit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        """Record one hit for ``key``; return True if allowed, False if the
        trailing-window count now exceeds ``limit`` (the caller should reject)."""
        ...
