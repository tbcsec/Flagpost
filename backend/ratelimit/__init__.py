"""Rate-limiter provider + FastAPI dependency (mirrors ``storage`` §13.3).

``get_rate_limiter`` is the single seam the submission route depends on. With a
``redis_url`` configured it builds one shared :class:`RedisRateLimiter`;
otherwise it falls back to the in-memory limiter (single-worker dev). Tests
override this dependency with a fresh in-memory double per test so limits don't
leak across cases (ADR-0006).
"""

from __future__ import annotations

from functools import lru_cache

from config import settings
from ratelimit.base import RateLimiter


@lru_cache(maxsize=1)
def _rate_limiter() -> RateLimiter:
    if settings.redis_url:
        from ratelimit.redis_limiter import RedisRateLimiter

        return RedisRateLimiter(
            settings.redis_url,
            max_connections=settings.redis_max_connections,
            acquire_timeout_seconds=settings.redis_acquire_timeout_seconds,
        )
    from ratelimit.memory import InMemoryRateLimiter

    return InMemoryRateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _rate_limiter()


async def step_up_allowed(rate_limiter: RateLimiter, user_id: str) -> bool:
    """Record an attempt at an endpoint that takes the caller's current password
    (change password, username or email; minting an API token), and whether it
    is within budget: 5 per 5 minutes per account, shared by all of them. One
    bucket each would add up to a larger guessing budget for whoever holds a
    stolen session (GHSA-vv68-w7qp-6cpf)."""
    return await rate_limiter.hit(f"step-up:{user_id}", limit=5, window_seconds=300)
