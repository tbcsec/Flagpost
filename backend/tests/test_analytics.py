"""Challenge & team analytics (Tier 3 Phase 5, ROADMAP #23): aggregate
correctness off a seeded submission set, tenant scoping, RBAC, and the optional
module's per-competition gate."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from db import SessionLocal
from models.competition import Competition
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


async def _submit(client, comp, chal, token, flag) -> bool:
    return (
        await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/submit",
            json={"flag": flag},
            headers=_auth(token),
        )
    ).json()["correct"]


async def _set_start(comp, when) -> None:
    async with SessionLocal() as session:
        competition = await session.get(Competition, comp)
        competition.start_at = when
        await session.commit()


async def _challenges_report(client, comp, token) -> dict:
    resp = await client.get(
        f"/api/competitions/{comp}/analytics/challenges", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_challenge_analytics_aggregates(client):
    comp = await _competition(client)
    await _set_start(comp, datetime.now(timezone.utc) - timedelta(hours=1))
    admin = await admin_token(client)
    chal_a = await _challenge(client, comp, "A", 100, "flag{a}")
    chal_b = await _challenge(client, comp, "B", 200, "flag{b}")
    ada = await _participant(client, comp, "ada@example.com")
    bob = await _participant(client, comp, "bob@example.com")
    cara = await _participant(client, comp, "cara@example.com")

    # A: ada + bob solve, cara fails once → solves 2, attempts 3, fails 1.
    assert await _submit(client, comp, chal_a, ada, "flag{a}") is True
    assert await _submit(client, comp, chal_a, bob, "flag{a}") is True
    assert await _submit(client, comp, chal_a, cara, "nope") is False
    # B: only ada solves → solves 1, attempts 1.
    assert await _submit(client, comp, chal_b, ada, "flag{b}") is True

    # A hint on B, revealed by ada; a ticket linked to A.
    hint = (
        await client.post(
            f"/api/competitions/{comp}/challenges/{chal_b}/hints",
            json={"body": "look closer", "cost": 10},
            headers=_auth(admin),
        )
    ).json()
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal_b}/hints/{hint['id']}/reveal",
        headers=_auth(ada),
    )
    await client.post(
        f"/api/competitions/{comp}/tickets",
        json={"subject": "stuck on A", "body": "help", "challenge_id": chal_a},
        headers=_auth(ada),
    )

    report = await _challenges_report(client, comp, admin)
    assert report["mode"] == "individual"
    assert report["subject_count"] == 3
    by_id = {c["title"]: c for c in report["challenges"]}

    a = by_id["A"]
    assert a["solve_count"] == 2
    assert a["attempt_count"] == 3
    assert a["fail_count"] == 1
    assert abs(a["completion_rate"] - 2 / 3) < 1e-6
    assert a["avg_solve_time_seconds"] is not None and a["avg_solve_time_seconds"] > 0
    assert a["ticket_count"] == 1
    assert a["hints_used"] == 0

    b = by_id["B"]
    assert b["solve_count"] == 1
    assert b["attempt_count"] == 1
    assert b["fail_count"] == 0
    assert abs(b["completion_rate"] - 1 / 3) < 1e-6
    assert b["hints_used"] == 1
    assert b["points"] == 200

    # An unsolved challenge reports None avg time, 0 completion.
    chal_c = await _challenge(client, comp, "C", 50, "flag{c}")
    report = await _challenges_report(client, comp, admin)
    c = {c["challenge_id"]: c for c in report["challenges"]}[chal_c]
    assert c["solve_count"] == 0
    assert c["avg_solve_time_seconds"] is None
    assert c["completion_rate"] == 0.0


async def test_team_analytics_ranks_and_counts(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    chal_a = await _challenge(client, comp, "A", 100, "flag{a}")
    chal_b = await _challenge(client, comp, "B", 200, "flag{b}")
    ada = await _participant(client, comp, "ada@example.com")
    bob = await _participant(client, comp, "bob@example.com")
    await _participant(client, comp, "cara@example.com")  # no solves

    await _submit(client, comp, chal_a, ada, "flag{a}")
    await _submit(client, comp, chal_b, ada, "flag{b}")  # ada: 300, 2 solves
    await _submit(client, comp, chal_a, bob, "flag{a}")  # bob: 100, 1 solve

    resp = await client.get(
        f"/api/competitions/{comp}/analytics/teams", headers=_auth(admin)
    )
    assert resp.status_code == 200, resp.text
    teams = resp.json()["teams"]
    by_name = {t["name"]: t for t in teams}
    assert by_name["ada"]["points"] == 300 and by_name["ada"]["solve_count"] == 2
    assert by_name["ada"]["rank"] == 1
    assert by_name["bob"]["points"] == 100 and by_name["bob"]["solve_count"] == 1
    assert by_name["cara"]["points"] == 0 and by_name["cara"]["solve_count"] == 0
    assert by_name["ada"]["last_solve_at"] is not None
    assert by_name["cara"]["last_solve_at"] is None


async def test_analytics_is_staff_only(client):
    comp = await _competition(client)
    await _challenge(client, comp, "A", 100, "flag{a}")
    ada = await _participant(client, comp, "ada@example.com")
    judge = await _judge(client, comp, "judge@example.com")

    # Participants lack view_competition_analytics.
    assert (
        await client.get(f"/api/competitions/{comp}/analytics/challenges", headers=_auth(ada))
    ).status_code == 403
    assert (
        await client.get(f"/api/competitions/{comp}/analytics/teams", headers=_auth(ada))
    ).status_code == 403
    # A Judge holds it.
    assert (
        await client.get(f"/api/competitions/{comp}/analytics/challenges", headers=_auth(judge))
    ).status_code == 200


async def test_analytics_never_leaks_another_competition(client):
    comp_a = await _competition(client)
    comp_b = await _competition(client)
    admin = await admin_token(client)
    a_chal = await _challenge(client, comp_a, "A-only", 100, "flag{a}")
    await _challenge(client, comp_b, "B-only", 100, "flag{b}")
    ada = await _participant(client, comp_a, "ada@example.com")
    await _submit(client, comp_a, a_chal, ada, "flag{a}")

    report = await _challenges_report(client, comp_a, admin)
    titles = {c["title"] for c in report["challenges"]}
    assert titles == {"A-only"}  # comp B's challenge never appears
    assert report["subject_count"] == 1  # only comp A's participant


async def test_analytics_module_can_be_disabled(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    await client.put(
        f"/api/competitions/{comp}/modules/analytics",
        json={"enabled": False},
        headers=_auth(admin),
    )
    assert (
        await client.get(f"/api/competitions/{comp}/analytics/challenges", headers=_auth(admin))
    ).status_code == 404
    # Re-enable → back to 200.
    await client.put(
        f"/api/competitions/{comp}/modules/analytics",
        json={"enabled": True},
        headers=_auth(admin),
    )
    assert (
        await client.get(f"/api/competitions/{comp}/analytics/challenges", headers=_auth(admin))
    ).status_code == 200
