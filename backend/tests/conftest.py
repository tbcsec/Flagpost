"""Shared test fixtures.

Tests run against a file-backed SQLite database (via aiosqlite) rather than
Postgres, so the suite needs no running infrastructure. The DB URL is set
*before* any app module is imported so the engine in ``db.py`` binds to it.
"""

import os
import tempfile

# Must run before importing db/config so settings pick these up.
_TMPDIR = tempfile.mkdtemp(prefix="ctf-test-")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMPDIR}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest_asyncio  # noqa: E402

from db import Base, engine  # noqa: E402
import models  # noqa: E402,F401  (populates Base.metadata)


@pytest_asyncio.fixture(autouse=True)
async def _create_schema():
    """Fresh schema per test — create all tables, drop them after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
