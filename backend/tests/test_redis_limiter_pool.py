"""The Redis rate limiter must use a bounded, blocking connection pool.

The 500-user load test (docs/load-testing/2026-08-12-500user-multicomp.md)
drove redis.asyncio's default uncapped ConnectionPool into
``get_available_connection: IndexError: pop from empty list`` — 150 × HTTP 500.
A BlockingConnectionPool with an explicit cap queues when exhausted instead of
racing. Construction is offline (redis.asyncio connects lazily on the first
command), so these tests need no Redis server.
"""

from redis.asyncio import BlockingConnectionPool

from config import settings
from ratelimit.redis_limiter import RedisRateLimiter


def test_limiter_builds_a_bounded_blocking_pool():
    limiter = RedisRateLimiter(
        "redis://localhost:1/0", max_connections=7, acquire_timeout_seconds=3.0
    )
    pool = limiter._redis.connection_pool
    assert isinstance(pool, BlockingConnectionPool)
    assert pool.max_connections == 7
    # BlockingConnectionPool queues for up to `timeout` seconds when exhausted
    # (the whole point — a burst degrades to latency, not IndexError/500s).
    assert pool.timeout == 3.0


def test_limiter_defaults_are_bounded_too():
    limiter = RedisRateLimiter("redis://localhost:1/0")
    pool = limiter._redis.connection_pool
    assert isinstance(pool, BlockingConnectionPool)
    assert pool.max_connections == 50


def test_config_knobs_exist_for_the_provider():
    # The provider (ratelimit._rate_limiter) passes these through; pin their
    # presence so a rename can't silently revert prod to an uncapped pool.
    assert settings.redis_max_connections > 0
    assert settings.redis_acquire_timeout_seconds > 0
