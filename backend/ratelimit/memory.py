"""In-memory sliding-window rate limiter (ADR-0006 — the test/no-infra double).

Keeps a deque of hit timestamps per key, prunes anything older than the window,
and admits a hit only while the surviving count is under the limit. Process-
local and non-durable — fine for the test suite and a single-worker dev run,
not for multi-worker production (that's what the Redis impl is for).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        bucket = self._hits[key]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True
