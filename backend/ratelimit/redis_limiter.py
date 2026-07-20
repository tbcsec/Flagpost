"""Redis-backed sliding-window rate limiter (production, §13.2).

Implemented with a per-key sorted set of hit timestamps: prune the window,
add this hit, count survivors, and set a TTL so idle keys expire. Runs as a
single pipeline so concurrent submissions from a scripted client can't race
past the limit. ``redis.asyncio`` is imported lazily so the package (and the
test suite) never needs the client unless a ``redis_url`` is configured.
"""

from __future__ import annotations

import time
from uuid import uuid4


class RedisRateLimiter:
    def __init__(self, redis_url: str) -> None:
        from redis.asyncio import from_url

        self._redis = from_url(redis_url, encoding="utf-8", decode_responses=True)

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        redis_key = f"ratelimit:{key}"
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(redis_key, 0, cutoff)
        # Unique member so identical-timestamp hits don't collapse into one.
        pipe.zadd(redis_key, {f"{now}:{uuid4().hex}": now})
        pipe.zcard(redis_key)
        pipe.expire(redis_key, window_seconds)
        _, _, count, _ = await pipe.execute()
        return count <= limit
