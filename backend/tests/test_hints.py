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
        {
            "id": hint,
            "challenge_id": chal,
            "cost": 0,
            "revealed": False,
            "body": None,
            "hidden": False,
            "release_at": None,
        }
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


# --- hidden / scheduled release (#213) ---------------------------------------


async def _add_hidden_hint(client, comp, chal, *, body="Locked", cost=0, release_at=None):
    admin = await admin_token(client)
    payload: dict = {"body": body, "cost": cost, "hidden": True}
    if release_at is not None:
        payload["release_at"] = release_at
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/hints",
        json=payload,
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _published_hint_events(hint_id: str) -> list:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "hint.published"
                )
            )
        ).scalars().all()
    return [r for r in rows if r.payload.get("hint_id") == hint_id]


async def test_hidden_hint_is_invisible_to_competitors_but_shown_to_staff(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp)
    hint = await _add_hidden_hint(client, comp, chal, body="Ssh, secret")
    admin = await admin_token(client)
    competitor = await _team_member(client, comp, "hid@example.com", "Hiders")

    # Competitor: the hidden hint isn't listed at all — its existence never leaks.
    listed = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{chal}/hints",
            headers=_auth(competitor),
        )
    ).json()
    assert listed == []

    # Staff: listed, flagged hidden, body visible for authoring.
    staff = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{chal}/hints", headers=_auth(admin)
        )
    ).json()
    assert [h["id"] for h in staff] == [hint]
    assert staff[0]["hidden"] is True
    assert staff[0]["body"] == "Ssh, secret"


async def test_reveal_rejects_a_hidden_hint(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp)
    hint = await _add_hidden_hint(client, comp, chal)
    competitor = await _team_member(client, comp, "peek2@example.com", "Peek2")
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/hints/{hint}/reveal",
        headers=_auth(competitor),
    )
    assert resp.status_code == 404


async def test_publishing_via_patch_makes_visible_and_emits(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp)
    hint = await _add_hidden_hint(client, comp, chal, body="Now you see me")
    admin = await admin_token(client)
    competitor = await _team_member(client, comp, "pub@example.com", "Pubs")

    resp = await client.patch(
        f"/api/competitions/{comp}/challenges/{chal}/hints/{hint}",
        json={"hidden": False},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["hidden"] is False

    listed = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{chal}/hints",
            headers=_auth(competitor),
        )
    ).json()
    assert [h["id"] for h in listed] == [hint]  # now visible to the competitor
    assert len(await _published_hint_events(hint)) == 1


async def test_editing_a_visible_hint_does_not_emit_published(client):
    comp = await _competition(client)
    chal = await _published_challenge(client, comp)
    hint = await _add_hint(client, comp, chal)  # visible by default
    admin = await admin_token(client)
    resp = await client.patch(
        f"/api/competitions/{comp}/challenges/{chal}/hints/{hint}",
        json={"cost": 25},
        headers=_auth(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["cost"] == 25
    # No hidden->visible transition ⇒ no hint.published.
    assert await _published_hint_events(hint) == []


async def test_scheduled_release_publishes_when_due(client):
    from utils.automation_scheduler import publish_scheduled_hints

    comp = await _competition(client)
    chal = await _published_challenge(client, comp)
    hint = await _add_hidden_hint(
        client, comp, chal, body="Timed", release_at="2020-01-01T00:00:00Z"
    )
    competitor = await _team_member(client, comp, "timed@example.com", "Timed")

    before = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{chal}/hints",
            headers=_auth(competitor),
        )
    ).json()
    assert before == []  # hidden until the scheduler runs

    await publish_scheduled_hints(SessionLocal)

    after = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{chal}/hints",
            headers=_auth(competitor),
        )
    ).json()
    assert [h["id"] for h in after] == [hint]
    assert len(await _published_hint_events(hint)) == 1


async def test_future_scheduled_hint_stays_hidden(client):
    from utils.automation_scheduler import publish_scheduled_hints

    comp = await _competition(client)
    chal = await _published_challenge(client, comp)
    hint = await _add_hidden_hint(client, comp, chal, release_at="2999-01-01T00:00:00Z")
    competitor = await _team_member(client, comp, "future@example.com", "Future")

    await publish_scheduled_hints(SessionLocal)

    listed = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{chal}/hints",
            headers=_auth(competitor),
        )
    ).json()
    assert listed == []  # not due yet
    assert await _published_hint_events(hint) == []
