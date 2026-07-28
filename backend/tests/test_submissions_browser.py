"""Submissions browser (ROADMAP #76) — staff-facing filterable, paginated read
over raw flag-submission attempts, for dispute resolution. Pure read model:
no migration, no new event; gated on the narrower ``view_submissions``
permission rather than ``view_competition_analytics``."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db import SessionLocal
from models.submission import Submission
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def _competition(client) -> str:
    admin = await admin_token(client)
    return (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": "individual", "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]


async def _challenge(client, comp, title, points, flag) -> str:
    admin = await admin_token(client)
    chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": title, "points": points, "flag": flag},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin)
    )
    return chal


async def _participant(client, comp, email) -> str:
    token = await _register(client, email)
    resp = await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return token


async def _judge(client, comp, email) -> str:
    token = await _register(client, email)
    me = (await client.get("/api/auth/me", headers=_auth(token))).json()
    async with SessionLocal() as session:
        from models.role import Role, RoleAssignment

        role = await session.scalar(select(Role).where(Role.name == "Judge"))
        session.add(RoleAssignment(user_id=me["id"], competition_id=comp, role_id=role.id))
        await session.commit()
    return token


async def _submit(client, comp, chal, token, flag) -> dict:
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": flag},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _browse(client, comp, token, **params) -> dict:
    resp = await client.get(
        f"/api/competitions/{comp}/analytics/submissions",
        params=params,
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_correctness_buckets_and_payload_visible(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    chal = await _challenge(client, comp, "A", 100, "flag{a}")
    ada = await _register(client, "ada@example.com")
    await client.post(f"/api/competitions/{comp}/join", headers=_auth(ada))

    await _submit(client, comp, chal, ada, "wrong-guess")  # incorrect
    await _submit(client, comp, chal, ada, "flag{a}")  # correct
    await _submit(client, comp, chal, ada, "flag{a}")  # duplicate (already solved)

    page = await _browse(client, comp, admin)
    assert page["total"] == 3
    by_value = {row["value"]: row for row in page["items"]}
    assert by_value["wrong-guess"]["correctness"] == "incorrect"
    assert by_value["wrong-guess"]["points_awarded"] == 0
    assert by_value["flag{a}"]["correctness"] == "correct"
    assert by_value["flag{a}"]["points_awarded"] == 100
    # The second, duplicate correct submission of the same value: filter by
    # correctness bucket instead since the value collides with the first.
    duplicates = await _browse(client, comp, admin, correctness="duplicate")
    assert duplicates["total"] == 1
    assert duplicates["items"][0]["points_awarded"] == 0
    assert duplicates["items"][0]["value"] == "flag{a}"

    incorrect = await _browse(client, comp, admin, correctness="incorrect")
    assert incorrect["total"] == 1
    correct = await _browse(client, comp, admin, correctness="correct")
    assert correct["total"] == 1


async def test_filters_by_challenge_user_and_free_text(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    chal_a = await _challenge(client, comp, "A", 100, "flag{a}")
    chal_b = await _challenge(client, comp, "B", 100, "flag{b}")
    ada = await _register(client, "ada@example.com")
    bob = await _register(client, "bob@example.com")
    for token in (ada, bob):
        await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    ada_me = (await client.get("/api/auth/me", headers=_auth(ada))).json()

    await _submit(client, comp, chal_a, ada, "flag{a}")
    await _submit(client, comp, chal_b, bob, "needle-in-haystack")

    by_challenge = await _browse(client, comp, admin, challenge_id=chal_a)
    assert by_challenge["total"] == 1
    assert by_challenge["items"][0]["challenge_id"] == chal_a

    by_user = await _browse(client, comp, admin, user_id=ada_me["id"])
    assert by_user["total"] == 1
    assert by_user["items"][0]["user_id"] == ada_me["id"]

    by_text = await _browse(client, comp, admin, q="haystack")
    assert by_text["total"] == 1
    assert by_text["items"][0]["value"] == "needle-in-haystack"

    by_time = await _browse(
        client,
        comp,
        admin,
        since=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    assert by_time["total"] == 0


async def test_pagination_bounds(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    chal = await _challenge(client, comp, "A", 100, "flag{a}")
    ada = await _register(client, "ada@example.com")
    await client.post(f"/api/competitions/{comp}/join", headers=_auth(ada))

    for _ in range(5):
        await _submit(client, comp, chal, ada, "nope")

    page1 = await _browse(client, comp, admin, limit=2, offset=0)
    assert page1["total"] == 5
    assert len(page1["items"]) == 2
    page2 = await _browse(client, comp, admin, limit=2, offset=2)
    assert len(page2["items"]) == 2
    # Newest-first, no overlap between pages.
    assert {r["id"] for r in page1["items"]}.isdisjoint({r["id"] for r in page2["items"]})

    resp = await client.get(
        f"/api/competitions/{comp}/analytics/submissions",
        params={"limit": 500},
        headers=_auth(admin),
    )
    assert resp.status_code == 422  # over the le=200 bound


async def test_permission_gating(client):
    comp = await _competition(client)
    await _challenge(client, comp, "A", 100, "flag{a}")
    ada = await _participant(client, comp, "ada@example.com")
    judge = await _judge(client, comp, "judge@example.com")

    # A plain participant lacks view_submissions (it isn't granted alongside
    # challenge_view/ticket_view/feedback_submit).
    assert (
        await client.get(
            f"/api/competitions/{comp}/analytics/submissions", headers=_auth(ada)
        )
    ).status_code == 403
    # A Judge holds it by default.
    assert (
        await client.get(
            f"/api/competitions/{comp}/analytics/submissions", headers=_auth(judge)
        )
    ).status_code == 200


async def test_module_disabled_404s(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    await client.put(
        f"/api/competitions/{comp}/modules/analytics",
        json={"enabled": False},
        headers=_auth(admin),
    )
    assert (
        await client.get(
            f"/api/competitions/{comp}/analytics/submissions", headers=_auth(admin)
        )
    ).status_code == 404
    await client.put(
        f"/api/competitions/{comp}/modules/analytics",
        json={"enabled": True},
        headers=_auth(admin),
    )
    assert (
        await client.get(
            f"/api/competitions/{comp}/analytics/submissions", headers=_auth(admin)
        )
    ).status_code == 200


async def test_never_leaks_another_competition(client):
    comp_a = await _competition(client)
    comp_b = await _competition(client)
    admin = await admin_token(client)
    chal_a = await _challenge(client, comp_a, "A-only", 100, "flag{a}")
    chal_b = await _challenge(client, comp_b, "B-only", 100, "flag{b}")
    ada = await _register(client, "ada@example.com")
    await client.post(f"/api/competitions/{comp_a}/join", headers=_auth(ada))
    await client.post(f"/api/competitions/{comp_b}/join", headers=_auth(ada))
    await _submit(client, comp_a, chal_a, ada, "flag{a}")
    await _submit(client, comp_b, chal_b, ada, "flag{b}")

    page = await _browse(client, comp_a, admin)
    assert page["total"] == 1
    assert page["items"][0]["challenge_id"] == chal_a


async def test_csv_export_matches_filters(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    chal = await _challenge(client, comp, "A", 100, "flag{a}")
    ada = await _register(client, "ada@example.com")
    await client.post(f"/api/competitions/{comp}/join", headers=_auth(ada))
    await _submit(client, comp, chal, ada, "flag{a}")
    await _submit(client, comp, chal, ada, "wrong")

    resp = await client.get(
        f"/api/competitions/{comp}/analytics/submissions/export",
        params={"correctness": "incorrect"},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("created_at,challenge_id,user_id,team_id,correctness,value,points_awarded")
    assert len(lines) == 2  # header + the one incorrect submission
    assert "wrong" in lines[1]


async def test_export_requires_permission(client):
    comp = await _competition(client)
    await _challenge(client, comp, "A", 100, "flag{a}")
    ada = await _participant(client, comp, "ada@example.com")
    assert (
        await client.get(
            f"/api/competitions/{comp}/analytics/submissions/export",
            headers=_auth(ada),
        )
    ).status_code == 403
