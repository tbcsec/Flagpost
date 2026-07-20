"""Hints (Phase 9, ROADMAP #15): authoring RBAC, body confidentiality until
reveal, idempotent per-subject reveal + cost, the challenge.hint_requested
event, team-shared reveals, and the hint-cost deduction on the scoreboard."""

from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from models.hint import HintReveal
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "password123",
            "display_name": email.split("@")[0],
        },
    )
    return resp.json()["access_token"]


async def _competition(client, mode: str = "team") -> str:
    admin = await admin_token(client)
    resp = await client.post(
        "/api/competitions",
        json={"name": "CTF", "participation_mode": mode},
        headers=_auth(admin),
    )
    return resp.json()["id"]


async def _published_challenge(client, comp: str, *, flag="flag{win}", points=500):
    admin = await admin_token(client)
    resp = await client.post(
        f"/api/competitions/{comp}/challenges",
        json={"title": "Chal", "points": points, "flag": flag},
        headers=_auth(admin),
    )
    chal = resp.json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin)
    )
    return chal


async def _add_hint(client, comp: str, chal: str, *, body="Try SQLi", cost=0) -> str:
    admin = await admin_token(client)
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/hints",
        json={"body": body, "cost": cost},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _team_member(client, comp: str, email: str, team: str) -> str:
    token = await _register(client, email)
    resp = await client.post(
        f"/api/competitions/{comp}/teams", json={"name": team}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    return token


async def _scoreboard_points(client, comp: str, token: str, name: str) -> int:
    board = (
        await client.get(f"/api/competitions/{comp}/scoreboard", headers=_auth(token))
    ).json()
    return next(e["points"] for e in board["entries"] if e["name"] == name)


async def test_authoring_requires_challenge_edit(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp)
    competitor = await _team_member(client, comp, "c@example.com", "Team C")
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/hints",
        json={"body": "secret", "cost": 10},
        headers=_auth(competitor),
    )
    assert resp.status_code == 403


async def test_body_hidden_until_revealed(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp)
    hint = await _add_hint(client, comp, chal, body="The flag is unioned", cost=0)
    competitor = await _team_member(client, comp, "peek@example.com", "Peekers")

    listed = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{chal}/hints",
            headers=_auth(competitor),
        )
    ).json()
    assert listed == [
        {"id": hint, "challenge_id": chal, "cost": 0, "revealed": False, "body": None}
    ]

    revealed = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/hints/{hint}/reveal",
        headers=_auth(competitor),
    )
    assert revealed.status_code == 200
    assert revealed.json()["revealed"] is True
    assert revealed.json()["body"] == "The flag is unioned"

    # Now the listing shows the body for this subject.
    relisted = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{chal}/hints",
            headers=_auth(competitor),
        )
    ).json()
    assert relisted[0]["body"] == "The flag is unioned"


async def test_reveal_is_idempotent_and_charges_once(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp)
    hint = await _add_hint(client, comp, chal, cost=50)
    competitor = await _team_member(client, comp, "once@example.com", "Once")
    url = f"/api/competitions/{comp}/challenges/{chal}/hints/{hint}/reveal"

    await client.post(url, headers=_auth(competitor))
    await client.post(url, headers=_auth(competitor))

    async with SessionLocal() as session:
        reveals = (
            await session.execute(select(HintReveal).where(HintReveal.hint_id == hint))
        ).scalars().all()
    assert len(reveals) == 1
    assert reveals[0].cost_charged == 50
    # And the event fires only on the first reveal.
    async with SessionLocal() as session:
        events = (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "challenge.hint_requested"
                )
            )
        ).scalars().all()
    assert len(events) == 1


async def test_team_reveal_shared_across_members(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp)
    hint = await _add_hint(client, comp, chal, body="shared", cost=25)

    captain = await _team_member(client, comp, "cap@example.com", "Squad")
    code = (
        await client.get(
            f"/api/competitions/{comp}/teams/me", headers=_auth(captain)
        )
    ).json()["invite_code"]
    mate = await _register(client, "mate@example.com")
    await client.post(
        f"/api/competitions/{comp}/teams/join",
        json={"invite_code": code},
        headers=_auth(mate),
    )

    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/hints/{hint}/reveal",
        headers=_auth(captain),
    )
    # The teammate sees it already revealed (and isn't charged again).
    mate_view = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{chal}/hints", headers=_auth(mate)
        )
    ).json()
    assert mate_view[0]["revealed"] is True
    assert mate_view[0]["body"] == "shared"
    async with SessionLocal() as session:
        reveals = (
            await session.execute(select(HintReveal).where(HintReveal.hint_id == hint))
        ).scalars().all()
    assert len(reveals) == 1


async def test_reveal_requires_a_team_in_team_mode(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp)
    hint = await _add_hint(client, comp, chal, cost=10)
    # Has challenge_view via a direct grant, but no team.
    from db import SessionLocal as SL
    from models.role import Role, RoleAssignment

    token = await _register(client, "teamless@example.com")
    me = (await client.get("/api/auth/me", headers=_auth(token))).json()
    async with SL() as session:
        role = await session.scalar(select(Role).where(Role.name == "Participant"))
        session.add(
            RoleAssignment(user_id=me["id"], competition_id=comp, role_id=role.id)
        )
        await session.commit()

    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/hints/{hint}/reveal",
        headers=_auth(token),
    )
    assert resp.status_code == 400
    assert "team" in resp.json()["detail"].lower()


async def test_hint_cost_deducts_from_scoreboard(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp, flag="flag{win}", points=500)
    hint = await _add_hint(client, comp, chal, cost=200)
    token = await _team_member(client, comp, "player@example.com", "Players")

    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": "flag{win}"},
        headers=_auth(token),
    )
    assert await _scoreboard_points(client, comp, token, "Players") == 500

    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/hints/{hint}/reveal",
        headers=_auth(token),
    )
    # 500 solve − 200 hint = 300.
    assert await _scoreboard_points(client, comp, token, "Players") == 300


async def test_hint_cost_never_drives_score_below_zero(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp, points=100)
    hint = await _add_hint(client, comp, chal, cost=250)  # more than any earnings
    token = await _team_member(client, comp, "broke@example.com", "Broke")

    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/hints/{hint}/reveal",
        headers=_auth(token),
    )
    assert await _scoreboard_points(client, comp, token, "Broke") == 0


async def test_delete_hint_requires_edit(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp)
    hint = await _add_hint(client, comp, chal)
    competitor = await _team_member(client, comp, "nodelete@example.com", "NoDelete")

    forbidden = await client.delete(
        f"/api/competitions/{comp}/challenges/{chal}/hints/{hint}",
        headers=_auth(competitor),
    )
    assert forbidden.status_code == 403

    admin = await admin_token(client)
    ok = await client.delete(
        f"/api/competitions/{comp}/challenges/{chal}/hints/{hint}",
        headers=_auth(admin),
    )
    assert ok.status_code == 204


async def test_non_editor_cannot_see_hints_on_a_draft(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    draft = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Draft", "flag": "flag{x}"},
            headers=_auth(admin),
        )
    ).json()["id"]
    await _add_hint(client, comp, draft, cost=10)
    competitor = await _team_member(client, comp, "drafter@example.com", "Drafters")

    resp = await client.get(
        f"/api/competitions/{comp}/challenges/{draft}/hints",
        headers=_auth(competitor),
    )
    assert resp.status_code == 404
