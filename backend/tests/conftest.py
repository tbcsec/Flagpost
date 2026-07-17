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
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-bytes-long-000000")

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from auth.seed import seed_system_roles  # noqa: E402
from db import Base, SessionLocal, engine  # noqa: E402
import models  # noqa: E402,F401  (populates Base.metadata)


@pytest_asyncio.fixture(autouse=True)
async def _create_schema():
    """Fresh schema per test — create all tables (+ seed system roles), drop after.

    Tests build the schema from metadata rather than running migrations, so the
    role seed the migration performs is reproduced here from the same specs
    (auth/seed.py) — see ADR-0006 on why the suite is SQLite/metadata-based.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        await seed_system_roles(session)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """In-process HTTP client against the real ASGI app (no port bound)."""
    import main

    transport = ASGITransport(app=main.app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as http_client:
        yield http_client
