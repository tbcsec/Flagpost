"""Connection-pool sizing (#174).

SQLAlchemy's stock pool (5 + 10 overflow = 15) was the concurrency ceiling
under a live event. The Postgres engine now gets an explicitly larger,
configurable pool; SQLite (the test/dev stack, ADR-0006) still gets none.
"""

from config import settings
from db import build_engine_kwargs


def test_sqlite_gets_no_pool_kwargs():
    kw = build_engine_kwargs("sqlite+aiosqlite:///./test.db")
    assert kw == {}


def test_postgres_gets_explicit_pool():
    kw = build_engine_kwargs("postgresql+asyncpg://u:p@host:5432/db")
    assert kw["pool_size"] == settings.db_pool_size
    assert kw["max_overflow"] == settings.db_max_overflow
    assert kw["pool_timeout"] == settings.db_pool_timeout
    assert kw["pool_pre_ping"] is True
    assert kw["pool_recycle"] == 1800


def test_pool_defaults_beat_sqlalchemy_stock():
    """The whole point of #174: the default ceiling is well above 5+10=15,
    and stays clear of Postgres' default max_connections (100)."""
    total = settings.db_pool_size + settings.db_max_overflow
    assert total > 15
    assert total < 100


def test_multiworker_splits_the_connection_budget(monkeypatch):
    """#189 Phase 3: the engine pool is per-process, so N workers must divide a
    fixed budget — not multiply a fixed 30 into Postgres max_connections."""
    monkeypatch.setattr(settings, "web_concurrency", 5)
    monkeypatch.setattr(settings, "db_connection_budget", 100)
    kw = build_engine_kwargs("postgresql+asyncpg://u:p@host:5432/db")
    assert kw["pool_size"] == 20  # 100 // 5
    assert kw["max_overflow"] == 10  # half the slice

    # The whole point: total connections across all workers stays bounded well
    # under a bumped Postgres max_connections (200 in compose).
    total = 5 * (kw["pool_size"] + kw["max_overflow"])
    assert total <= 200


def test_single_worker_pool_is_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "web_concurrency", 1)
    kw = build_engine_kwargs("postgresql+asyncpg://u:p@host:5432/db")
    assert kw["pool_size"] == settings.db_pool_size
    assert kw["max_overflow"] == settings.db_max_overflow
