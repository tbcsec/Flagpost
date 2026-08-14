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
from utils.coalesce import reset_all_coalescers  # noqa: E402
from utils.event_bus import event_bus  # noqa: E402


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
    # Drain any fire-and-forget background handlers (ADR-0012 — e.g. the
    # automation engine on competition.created) *before* dropping the schema, so
    # a leaked task never runs against the next test's fresh DB and flakes it.
    await event_bus.wait_for_background()
    # Likewise cancel any pending activity-coalescer windows (#175/#188), so a
    # trailing broadcast armed in this test can't fire during the next.
    reset_all_coalescers()
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

from ratelimit import get_rate_limiter  # noqa: E402
from ratelimit.memory import InMemoryRateLimiter  # noqa: E402
from storage import get_storage  # noqa: E402
from storage.memory import InMemoryStorage  # noqa: E402


@pytest.fixture(autouse=True)
def _competitions_default_running(request):
    """Gameplay is exercised against a *running* competition, but production
    defaults a new competition to ``not_started`` (#221 — the gameplay gate that
    closes challenge viewing/submission and the scoreboard to competitors). So for
    the suite, auto-start a freshly-created competition, sparing the many
    competitor-facing tests from each starting theirs. Tests that drive the
    lifecycle itself opt out with ``@pytest.mark.competition_lifecycle`` and get
    the real ``not_started`` default (see tests/test_competition_status.py).

    Implemented as a foreground ``competition.created`` listener (a direct row
    UPDATE, robust unlike mutating the cached column default) that only flips the
    status — it deliberately leaves ``started_event_fired`` alone so scheduler /
    lifecycle-event tests still fire ``competition.started`` normally. Registered
    only for the current test and removed after, so opted-out tests are untouched."""
    if request.node.get_closest_marker("competition_lifecycle"):
        yield
        return
    from db import SessionLocal
    from models.competition import Competition
    from utils.event_bus import event_bus

    async def _auto_start(_event_name, payload):
        cid = payload.get("competition_id")
        if not cid:
            return
        async with SessionLocal() as session:
            comp = await session.get(Competition, cid)
            if comp is not None and comp.status == "not_started":
                comp.status = "running"
                await session.commit()

    event_bus.subscribe("competition.created", _auto_start, owner="_test_autostart")
    try:
        yield
    finally:
        event_bus.unsubscribe_owner("_test_autostart")


@pytest.fixture
def object_storage() -> InMemoryStorage:
    """In-memory object storage double so the suite needs no MinIO (ADR-0006)."""
    return InMemoryStorage()


@pytest.fixture
def rate_limiter() -> InMemoryRateLimiter:
    """Fresh in-memory submission rate limiter per test — no Redis, no leaking
    counts across cases (ADR-0006)."""
    return InMemoryRateLimiter()


@pytest_asyncio.fixture
async def client(object_storage, rate_limiter):
    """In-process HTTP client against the real ASGI app (no port bound)."""
    import main

    main.app.dependency_overrides[get_storage] = lambda: object_storage
    main.app.dependency_overrides[get_rate_limiter] = lambda: rate_limiter
    transport = ASGITransport(app=main.app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as http_client:
        yield http_client
    main.app.dependency_overrides.clear()
