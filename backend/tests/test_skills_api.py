"""Skills web endpoints (#364, ADR-0039): the self read, the admin matrix + its
RBAC and pagination, the cross-competition end-to-end through the real submit
route, and the site-wide off switch. The aggregation itself is unit-tested in
`test_skills`."""

import pytest

from config import settings
from db import SessionLocal
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from tests.conftest import admin_token


@pytest.fixture(autouse=True)
def _no_skills_cache():
    """The skills cache is process-global and its matrix key is constant, so a
    stale entry would leak across tests (and hide a just-made solve). Off here so
    each read recomputes; the invalidation path is exercised in `test_skills_events`."""
    original = settings.skills_cache_seconds
    settings.skills_cache_seconds = 0
    yield
    settings.skills_cache_seconds = original


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, name: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={"display_name": name, "password": "password123"},
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _competition(client, admin: str) -> str:
    resp = await client.post(
        "/api/competitions",
        json={"name": "CTF", "participation_mode": "individual", "visibility": "public"},
        headers=_auth(admin),
    )
    return resp.json()["id"]


async def _category(client, admin: str, comp: str, name: str) -> str:
    resp = await client.post(
        f"/api/competitions/{comp}/categories", json={"name": name}, headers=_auth(admin)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _challenge(client, admin: str, comp: str, *, flag: str, category_id: str, title="C") -> str:
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": title, "flag": flag, "points": 100, "category_id": category_id},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    await client.post(f"/api/competitions/{comp}/challenges/{cid}/publish", headers=_auth(admin))
    return cid


async def _join(client, token: str, comp: str) -> None:
    await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))


async def _solve(client, token: str, comp: str, cid: str, flag: str):
    return await client.post(
        f"/api/competitions/{comp}/challenges/{cid}/submit",
        json={"flag": flag},
        headers=_auth(token),
    )


async def _set_skills_enabled(value: bool) -> None:
    async with SessionLocal() as db:
        row = await db.get(SiteSettings, SITE_SETTINGS_ID)
        if row is None:
            row = SiteSettings(id=SITE_SETTINGS_ID)
            db.add(row)
        row.skills_enabled = value
        await db.commit()


# --- self read ---------------------------------------------------------------


async def test_my_skills_requires_auth(client):
    resp = await client.get("/api/me/skills")
    assert resp.status_code == 401


async def test_my_skills_web_spans_competitions(client):
    admin = await admin_token(client)
    # Two separate events, each with a "Web" category the user solves in.
    web = []
    for i in range(2):
        comp = await _competition(client, admin)
        cat = await _category(client, admin, comp, "Web")
        chal = await _challenge(client, admin, comp, flag=f"flag{{{i}}}", category_id=cat)
        web.append((comp, chal, f"flag{{{i}}}"))
    ada, _ = await _register(client, "ada")
    for comp, chal, flag in web:
        await _join(client, ada, comp)
        r = await _solve(client, ada, comp, chal, flag)
        assert r.json()["correct"] is True, r.text

    body = (await client.get("/api/me/skills", headers=_auth(ada))).json()
    # One merged axis that grew across both events; unbounded cumulative count.
    assert body["skills"] == [{"skill": "web", "score": 2}]
    assert body["total"] == 2
    assert body["competitions_played"] == 2


# --- admin matrix ------------------------------------------------------------


async def test_admin_matrix_requires_global_analytics(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    cat = await _category(client, admin, comp, "Web")
    chal = await _challenge(client, admin, comp, flag="flag{a}", category_id=cat)
    ada, _ = await _register(client, "ada")
    await _join(client, ada, comp)
    await _solve(client, ada, comp, chal, "flag{a}")

    # A participant has no view_global_analytics → 403.
    forbidden = await client.get("/api/admin/skills", headers=_auth(ada))
    assert forbidden.status_code == 403

    matrix = (await client.get("/api/admin/skills", headers=_auth(admin))).json()
    assert matrix["skills"] == ["web"]
    names = {u["display_name"]: u for u in matrix["users"]}
    assert names["ada"]["scores"] == {"web": 1}
    assert names["ada"]["total"] == 1


async def test_admin_matrix_paginates_over_users(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    cat = await _category(client, admin, comp, "Web")
    chal = await _challenge(client, admin, comp, flag="flag{a}", category_id=cat)
    for i in range(3):
        token, _ = await _register(client, f"p{i}")
        await _join(client, token, comp)
        await _solve(client, token, comp, chal, "flag{a}")

    first = (await client.get("/api/admin/skills?limit=2&offset=0", headers=_auth(admin))).json()
    assert first["total_users"] == 3
    assert len(first["users"]) == 2
    second = (await client.get("/api/admin/skills?limit=2&offset=2", headers=_auth(admin))).json()
    assert len(second["users"]) == 1
    # No overlap between the pages.
    ids = {u["user_id"] for u in first["users"]} | {u["user_id"] for u in second["users"]}
    assert len(ids) == 3


# --- site-wide off switch ----------------------------------------------------


async def test_both_reads_404_when_skills_disabled(client):
    admin = await admin_token(client)
    ada, _ = await _register(client, "ada")
    await _set_skills_enabled(False)

    assert (await client.get("/api/me/skills", headers=_auth(ada))).status_code == 404
    assert (await client.get("/api/admin/skills", headers=_auth(admin))).status_code == 404


async def test_a_solve_invalidates_the_cached_web(client):
    # The web is a cached read; a solve must drop it so it never lags the scoring
    # event (the module subscribes invalidate_skills to challenge.solved).
    settings.skills_cache_seconds = 30  # cache ON; the autouse fixture restores after
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    cat = await _category(client, admin, comp, "Web")
    chal = await _challenge(client, admin, comp, flag="flag{a}", category_id=cat)
    ada, _ = await _register(client, "ada")
    await _join(client, ada, comp)

    # Prime the cache while ada has nothing.
    primed = (await client.get("/api/me/skills", headers=_auth(ada))).json()
    assert primed["total"] == 0
    r = await _solve(client, ada, comp, chal, "flag{a}")
    assert r.json()["correct"] is True
    # The next read reflects the solve — the cache was dropped, not waited out.
    after = (await client.get("/api/me/skills", headers=_auth(ada))).json()
    assert after["skills"] == [{"skill": "web", "score": 1}]


async def test_operational_settings_round_trips_skills_enabled(client):
    admin = await admin_token(client)
    # Default on, surfaced on both the admin operational read and the public read.
    op = (await client.get("/api/site-settings/operational", headers=_auth(admin))).json()
    assert op["skills_enabled"] is True
    assert (await client.get("/api/site-settings")).json()["skills_enabled"] is True

    saved = await client.put(
        "/api/site-settings/operational",
        json={"registration_open": True, "skills_enabled": False},
        headers=_auth(admin),
    )
    assert saved.status_code == 200 and saved.json()["skills_enabled"] is False
    assert (await client.get("/api/site-settings")).json()["skills_enabled"] is False
