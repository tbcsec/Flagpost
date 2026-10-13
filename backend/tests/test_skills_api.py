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
    # Enriched cell (#435): ada joined (membership = opportunity), one published
    # web challenge, one solve worth its 100 points.
    assert names["ada"]["scores"] == {
        "web": {
            "weighted": 100, "solved": 1, "available": 1, "pct": 0,
            "attempts": 1, "hints": 0, "first_bloods": 1,
        }
    }
    assert names["ada"]["total"] == 1
    assert names["ada"]["total_weighted"] == 100
    assert matrix["population"] == {"web": {"solvers": 1, "mean_weighted": 100}}


async def test_admin_matrix_sorts_by_column(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    web = await _category(client, admin, comp, "Web")
    pwn = await _category(client, admin, comp, "Pwn")
    w = await _challenge(client, admin, comp, flag="flag{w}", category_id=web, title="w")
    p1 = await _challenge(client, admin, comp, flag="flag{p1}", category_id=pwn, title="p1")
    p2 = await _challenge(client, admin, comp, flag="flag{p2}", category_id=pwn, title="p2")
    webber, _ = await _register(client, "webber")
    await _join(client, webber, comp)
    await _solve(client, webber, comp, w, "flag{w}")
    pwner, _ = await _register(client, "pwner")
    await _join(client, pwner, comp)
    await _solve(client, pwner, comp, p1, "flag{p1}")
    await _solve(client, pwner, comp, p2, "flag{p2}")

    # Default: total weighted desc → pwner (200) first.
    default = (await client.get("/api/admin/skills", headers=_auth(admin))).json()
    assert [u["display_name"] for u in default["users"]] == ["pwner", "webber"]
    # Sorting by the web column puts the web solver first…
    by_web = (
        await client.get("/api/admin/skills?sort=web", headers=_auth(admin))
    ).json()
    assert by_web["users"][0]["display_name"] == "webber"
    # …and ascending flips it.
    asc = (
        await client.get(
            "/api/admin/skills?sort=web&direction=asc", headers=_auth(admin)
        )
    ).json()
    assert asc["users"][-1]["display_name"] == "webber"
    # An unknown column is a 422, not a silent default.
    bad = await client.get("/api/admin/skills?sort=nope", headers=_auth(admin))
    assert bad.status_code == 422


async def test_admin_matrix_csv_export(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    cat = await _category(client, admin, comp, "Web")
    chal = await _challenge(client, admin, comp, flag="flag{a}", category_id=cat)
    ada, _ = await _register(client, "ada")
    await _join(client, ada, comp)
    await _solve(client, ada, comp, chal, "flag{a}")

    # Participant: same RBAC wall as the matrix itself.
    assert (
        await client.get("/api/admin/skills/export", headers=_auth(ada))
    ).status_code == 403

    resp = await client.get("/api/admin/skills/export", headers=_auth(admin))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("User,Total points,Total solves")
    assert "web (points)" in lines[0] and "web (available)" in lines[0]
    ada_line = next(line for line in lines if line.startswith("ada"))
    assert "100" in ada_line


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


async def test_admin_user_drilldown(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    cat = await _category(client, admin, comp, "Web")
    chal = await _challenge(client, admin, comp, flag="flag{a}", category_id=cat)
    ada, ada_id = await _register(client, "ada")
    await _join(client, ada, comp)
    # A wrong guess before the solve — the drill-down shows the struggle.
    await _solve(client, ada, comp, chal, "flag{wrong}")
    await _solve(client, ada, comp, chal, "flag{a}")

    # Same RBAC wall as the matrix.
    assert (
        await client.get(f"/api/admin/skills/users/{ada_id}", headers=_auth(ada))
    ).status_code == 403
    # Unknown user: undisclosing 404.
    assert (
        await client.get("/api/admin/skills/users/nope", headers=_auth(admin))
    ).status_code == 404

    detail = (
        await client.get(f"/api/admin/skills/users/{ada_id}", headers=_auth(admin))
    ).json()
    assert detail["display_name"] == "ada"
    assert detail["total"] == 1
    assert detail["skills"][0]["skill"] == "web"
    assert detail["skills"][0]["attempts"] == 2
    assert detail["skills"][0]["first_bloods"] == 1
    [solve] = detail["solves"]
    assert solve["first_blood"] is True and solve["attempts"] == 2


async def test_window_param_is_allowlisted(client):
    admin = await admin_token(client)
    for path in (
        "/api/admin/skills?window=7",
        "/api/admin/skills/export?window=yesterday",
        "/api/admin/skills/users/someone?window=0",
    ):
        resp = await client.get(path, headers=_auth(admin))
        assert resp.status_code == 422, path
    # The allowlisted values pass straight through.
    ok = await client.get("/api/admin/skills?window=90", headers=_auth(admin))
    assert ok.status_code == 200


async def test_admin_matrix_search_filters_by_display_name(client):
    admin = await admin_token(client)
    comp = await _competition(client, admin)
    cat = await _category(client, admin, comp, "Web")
    chal = await _challenge(client, admin, comp, flag="flag{a}", category_id=cat)
    for name in ("alice", "alpha", "bob"):
        tok, _ = await _register(client, name)
        await _join(client, tok, comp)
        await _solve(client, tok, comp, chal, "flag{a}")

    # Substring, case-insensitive, over every tracked user — "al" matches
    # alice + alpha (and searching finds them regardless of which page they'd
    # otherwise land on).
    res = (
        await client.get("/api/admin/skills?q=AL", headers=_auth(admin))
    ).json()
    assert res["total_users"] == 2
    assert {u["display_name"] for u in res["users"]} == {"alice", "alpha"}
    # A specific name narrows to one.
    one = (await client.get("/api/admin/skills?q=bob", headers=_auth(admin))).json()
    assert [u["display_name"] for u in one["users"]] == ["bob"]
    # No match → empty page, but the population footer stays whole (community ref).
    none = (await client.get("/api/admin/skills?q=zzz", headers=_auth(admin))).json()
    assert none["total_users"] == 0 and none["users"] == []
    assert none["population"]["web"]["solvers"] == 3
