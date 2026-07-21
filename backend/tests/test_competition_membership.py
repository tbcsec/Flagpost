"""Competition join + visibility (pre-Tier-2 gap fixes).

Joining a competition is how a competitor gains the Participant role — and, for
individual-mode competitions (no teams), the *only* way in. Visibility is
enforced on reads: a private competition is hidden from non-members.
"""

from sqlalchemy import select

from auth.deps import user_has_permission
from db import SessionLocal
from models.audit_log import AuditLogEntry
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email, name="User") -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": name},
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _make_competition(client, *, visibility="public", mode="individual") -> dict:
    admin = await admin_token(client)
    resp = await client.post(
        "/api/competitions",
        json={"name": "CTF", "participation_mode": mode, "visibility": visibility},
        headers=_auth(admin),
    )
    return resp.json()


async def test_public_self_serve_join_grants_participant_access(client):
    comp = await _make_competition(client, visibility="public", mode="individual")
    token, user_id = await _register(client, "solo@example.com")

    # Individual-mode: no team to join — the competition join is the only path in.
    resp = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == comp["id"]

    async with SessionLocal() as session:
        assert await user_has_permission(
            session, user_id, "challenge_view", comp["id"]
        )
    # ...and the join event landed.
    async with SessionLocal() as session:
        events = (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "competition.member_joined"
                )
            )
        ).scalars().all()
    assert len(events) == 1


async def test_join_is_idempotent(client):
    comp = await _make_competition(client, visibility="public")
    token, _ = await _register(client, "twice@example.com")

    await client.post(f"/api/competitions/{comp['id']}/join", headers=_auth(token))
    await client.post(f"/api/competitions/{comp['id']}/join", headers=_auth(token))

    async with SessionLocal() as session:
        events = (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "competition.member_joined"
                )
            )
        ).scalars().all()
    # Re-joining doesn't grant a second role or re-emit.
    assert len(events) == 1


async def test_private_competition_rejects_self_serve_join(client):
    comp = await _make_competition(client, visibility="private")
    token, _ = await _register(client, "sneaky@example.com")
    resp = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert resp.status_code == 403


async def test_join_private_by_invite_code(client):
    comp = await _make_competition(client, visibility="private", mode="individual")
    token, user_id = await _register(client, "invited@example.com")

    resp = await client.post(
        "/api/competitions/join",
        json={"invite_code": comp["invite_code"]},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    async with SessionLocal() as session:
        assert await user_has_permission(
            session, user_id, "challenge_view", comp["id"]
        )


async def test_join_by_bad_code_404s(client):
    await _make_competition(client, visibility="private")
    token, _ = await _register(client, "wrongcode@example.com")
    resp = await client.post(
        "/api/competitions/join",
        json={"invite_code": "not-a-real-code"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_private_competition_hidden_from_non_members(client):
    private = await _make_competition(client, visibility="private")
    public = await _make_competition(client, visibility="public")
    token, _ = await _register(client, "outsider@example.com")

    # Listing hides the private competition.
    listing = await client.get("/api/competitions", headers=_auth(token))
    ids = {c["id"] for c in listing.json()}
    assert public["id"] in ids
    assert private["id"] not in ids

    # And a direct read 404s (existence not disclosed).
    direct = await client.get(
        f"/api/competitions/{private['id']}", headers=_auth(token)
    )
    assert direct.status_code == 404


async def test_member_sees_private_competition_after_joining(client):
    private = await _make_competition(client, visibility="private")
    token, _ = await _register(client, "member@example.com")
    await client.post(
        "/api/competitions/join",
        json={"invite_code": private["invite_code"]},
        headers=_auth(token),
    )
    listing = await client.get("/api/competitions", headers=_auth(token))
    assert private["id"] in {c["id"] for c in listing.json()}


async def test_admin_sees_all_competitions(client):
    private = await _make_competition(client, visibility="private")
    admin = await admin_token(client)
    listing = await client.get("/api/competitions", headers=_auth(admin))
    assert private["id"] in {c["id"] for c in listing.json()}
