"""Scoreboard REST endpoint + ranking rules (Phase 7, ROADMAP #13): ordering,
the earliest-reach tie-break, team vs individual subjects, zero-point
inclusion, RBAC, and scoping."""

from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": email.split("@")[0],
        },
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _make_competition(client, mode: str = "team") -> str:
    admin = await admin_token(client)
    resp = await client.post(
        "/api/competitions",
        json={"name": "CTF", "participation_mode": mode},
        headers=_auth(admin),
    )
    return resp.json()["id"]


async def _published_challenge(client, comp: str, flag: str, points: int) -> str:
    admin = await admin_token(client)
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": f"Chal {flag}", "points": points, "flag": flag},
        headers=_auth(admin),
    )
    chal = resp.json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin)
    )
    return chal


async def _team_member(client, comp: str, email: str, team: str) -> str:
    token, _ = await _register(client, email)
    await client.post(
        f"/api/competitions/{comp}/teams", json={"name": team}, headers=_auth(token)
    )
    return token


async def _submit(client, comp: str, chal: str, token: str, flag: str):
    return await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": flag},
        headers=_auth(token),
    )


async def test_team_scoreboard_ranks_by_points(client):
    comp = await _make_competition(client)
    c1 = await _published_challenge(client, comp, "flag{a}", 100)
    c2 = await _published_challenge(client, comp, "flag{b}", 250)

    alice = await _team_member(client, comp, "alice@example.com", "Alpha")
    bob = await _team_member(client, comp, "bob@example.com", "Bravo")
    # Alpha 100, Bravo 350.
    await _submit(client, comp, c1, alice, "flag{a}")
    await _submit(client, comp, c1, bob, "flag{a}")
    await _submit(client, comp, c2, bob, "flag{b}")

    resp = await client.get(
        f"/api/competitions/{comp}/scoreboard", headers=_auth(alice)
    )
    assert resp.status_code == 200, resp.text
    board = resp.json()
    assert board["mode"] == "team"
    assert [(e["rank"], e["name"], e["points"]) for e in board["entries"]] == [
        (1, "Bravo", 350),
        (2, "Alpha", 100),
    ]


async def test_tie_broken_by_earliest_reach(client):
    comp = await _make_competition(client)
    chal = await _published_challenge(client, comp, "flag{tie}", 100)

    first = await _team_member(client, comp, "first@example.com", "Faster")
    second = await _team_member(client, comp, "second@example.com", "Slower")
    await _submit(client, comp, chal, first, "flag{tie}")
    await _submit(client, comp, chal, second, "flag{tie}")

    board = (
        await client.get(
            f"/api/competitions/{comp}/scoreboard", headers=_auth(first)
        )
    ).json()
    # Equal points — whoever reached the score first ranks higher (§15).
    assert [e["name"] for e in board["entries"]] == ["Faster", "Slower"]


async def test_zero_point_teams_appear_below_scorers(client):
    comp = await _make_competition(client)
    chal = await _published_challenge(client, comp, "flag{a}", 100)
    scorer = await _team_member(client, comp, "scorer@example.com", "Scorers")
    await _team_member(client, comp, "idle@example.com", "Idlers")
    await _submit(client, comp, chal, scorer, "flag{a}")

    board = (
        await client.get(
            f"/api/competitions/{comp}/scoreboard", headers=_auth(scorer)
        )
    ).json()
    assert [(e["name"], e["points"]) for e in board["entries"]] == [
        ("Scorers", 100),
        ("Idlers", 0),
    ]
    assert board["entries"][1]["last_solve_at"] is None


async def test_individual_scoreboard_ranks_users(client):
    from db import SessionLocal
    from sqlalchemy import select
    from models.role import Role, RoleAssignment

    comp = await _make_competition(client, mode="individual")
    chal = await _published_challenge(client, comp, "flag{solo}", 150)

    solo, solo_id = await _register(client, "solo@example.com")
    _, idle_id = await _register(client, "idle@example.com")
    async with SessionLocal() as session:
        role = await session.scalar(select(Role).where(Role.name == "Participant"))
        session.add(
            RoleAssignment(user_id=solo_id, competition_id=comp, role_id=role.id)
        )
        session.add(
            RoleAssignment(user_id=idle_id, competition_id=comp, role_id=role.id)
        )
        await session.commit()
    await _submit(client, comp, chal, solo, "flag{solo}")

    board = (
        await client.get(f"/api/competitions/{comp}/scoreboard", headers=_auth(solo))
    ).json()
    assert board["mode"] == "individual"
    assert [(e["name"], e["points"]) for e in board["entries"]] == [
        ("solo", 150),
        ("idle", 0),
    ]
    assert board["entries"][0]["subject_id"] == solo_id


async def test_scoreboard_requires_competition_access(client):
    comp = await _make_competition(client)
    outsider, _ = await _register(client, "outsider@example.com")
    resp = await client.get(
        f"/api/competitions/{comp}/scoreboard", headers=_auth(outsider)
    )
    assert resp.status_code == 403


async def test_scoreboard_404_for_missing_competition(client):
    admin = await admin_token(client)
    resp = await client.get(
        "/api/competitions/nope/scoreboard", headers=_auth(admin)
    )
    assert resp.status_code == 404


# --- scoreboard freeze (Phase 9) ---------------------------------------------


async def test_freeze_hides_later_solves_from_players_but_not_live_staff(client):
    comp = await _make_competition(client, mode="individual")
    c1 = await _published_challenge(client, comp, "flag{a}", 100)
    c2 = await _published_challenge(client, comp, "flag{b}", 250)
    admin = await admin_token(client)
    player, pid = await _register(client, "ada@example.com")
    async with __import__("db").SessionLocal() as s:
        from sqlalchemy import select
        from models.role import Role, RoleAssignment
        role = await s.scalar(select(Role).where(Role.name == "Participant"))
        s.add(RoleAssignment(user_id=pid, competition_id=comp, role_id=role.id))
        await s.commit()

    # Solve the first challenge, then freeze, then solve the second.
    await _submit(client, comp, c1, player, "flag{a}")
    fr = await client.post(f"/api/competitions/{comp}/scoreboard/freeze", json={}, headers=_auth(admin))
    assert fr.status_code == 200
    await _submit(client, comp, c2, player, "flag{b}")

    # The player sees the frozen board: only the pre-freeze 100 points.
    board = (await client.get(f"/api/competitions/{comp}/scoreboard", headers=_auth(player))).json()
    assert board["frozen"] is True
    assert board["entries"][0]["points"] == 100

    # Staff can still read the live standings (both solves = 350).
    live = (await client.get(f"/api/competitions/{comp}/scoreboard?live=true", headers=_auth(admin))).json()
    assert live["frozen"] is False
    assert live["entries"][0]["points"] == 350

    # A player asking for ?live=true is ignored (no permission) — stays frozen.
    still = (await client.get(f"/api/competitions/{comp}/scoreboard?live=true", headers=_auth(player))).json()
    assert still["entries"][0]["points"] == 100

    # Unfreeze → the board is live for everyone again.
    await client.post(f"/api/competitions/{comp}/scoreboard/unfreeze", headers=_auth(admin))
    after = (await client.get(f"/api/competitions/{comp}/scoreboard", headers=_auth(player))).json()
    assert after["frozen"] is False
    assert after["entries"][0]["points"] == 350


async def test_freeze_requires_permission(client):
    comp = await _make_competition(client, mode="individual")
    player, _ = await _register(client, "nobody@example.com")
    resp = await client.post(
        f"/api/competitions/{comp}/scoreboard/freeze", json={}, headers=_auth(player)
    )
    assert resp.status_code == 403
