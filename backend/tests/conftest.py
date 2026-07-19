"""Shared test fixtures.

Tests run against a file-backed SQLite database (via aiosqlite) rather than
Postgres, so the suite needs no running infrastructure. The DB URL is set
*before* any app module is imported so the engine in ``db.py`` binds to it.
"""

import os
import tempfile

# Must run before importing db/config so settings pick these up.
_TMPDIR = tempfile.mkdtemp(prefix="flagpost-test-")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMPDIR}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-bytes-long-000000")

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from auth.seed import (  # noqa: E402
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
    seed_admin_user,
    seed_system_roles,
)
from db import Base, SessionLocal, engine  # noqa: E402
import models  # noqa: E402,F401  (populates Base.metadata)


@pytest_asyncio.fixture(autouse=True)
async def _create_schema():
    """Fresh schema per test — create all tables, seed roles + admin, drop after.

    Tests build the schema from metadata rather than running migrations, so the
    role + admin seed the migration/startup perform is reproduced here from the
    same specs (auth/seed.py) — see ADR-0006 on why the suite is SQLite-based.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        await seed_system_roles(session)
        await seed_admin_user(session)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def admin_token(client) -> str:
    """Log in as the seeded default administrator and return an access token."""
    resp = await client.post(
        "/api/auth/login",
        json={"email": DEFAULT_ADMIN_EMAIL, "password": DEFAULT_ADMIN_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


import pytest  # noqa: E402

from storage import get_storage  # noqa: E402
from storage.memory import InMemoryStorage  # noqa: E402


@pytest.fixture
def object_storage() -> InMemoryStorage:
    """In-memory object storage double so the suite needs no MinIO (ADR-0006)."""
    return InMemoryStorage()


@pytest_asyncio.fixture
async def client(object_storage):
    """In-process HTTP client against the real ASGI app (no port bound)."""
    import main

    main.app.dependency_overrides[get_storage] = lambda: object_storage
    transport = ASGITransport(app=main.app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as http_client:
        yield http_client
    main.app.dependency_overrides.clear()
