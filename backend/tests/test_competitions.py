"""Competition endpoints: RBAC enforcement + event emission (§6, §7.6)."""

from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry


async def _register(client, email, name="User"):
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": name},
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_admin_can_create_competition_and_event_is_emitted(client):
    token, user_id = await _register(client, "admin@example.com", "Admin")  # first == admin

    resp = await client.post(
        "/api/competitions",
        json={"name": "Spring CTF", "participation_mode": "individual"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["name"] == "Spring CTF"
    assert created["participation_mode"] == "individual"

    # competition.created lands in the audit log with the tenant + actor lifted.
    async with SessionLocal() as session:
        entry = (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "competition.created"
                )
            )
        ).scalar_one()
    assert entry.competition_id == created["id"]
    assert entry.user_id == user_id


async def test_participant_cannot_create_competition(client):
    # First user is admin; the second is a plain Participant.
    await _register(client, "admin@example.com", "Admin")
    token, _ = await _register(client, "participant@example.com", "Player")

    resp = await client.post(
        "/api/competitions",
        json={"name": "Nope"},
        headers=_auth(token),
    )
    assert resp.status_code == 403


async def test_create_requires_authentication(client):
    resp = await client.post("/api/competitions", json={"name": "Anon"})
    assert resp.status_code == 401


async def test_list_and_get_competition(client):
    token, _ = await _register(client, "admin@example.com", "Admin")
    created = (
        await client.post(
            "/api/competitions", json={"name": "Autumn CTF"}, headers=_auth(token)
        )
    ).json()

    listed = await client.get("/api/competitions", headers=_auth(token))
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [created["id"]]

    fetched = await client.get(
        f"/api/competitions/{created['id']}", headers=_auth(token)
    )
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Autumn CTF"

    missing = await client.get("/api/competitions/does-not-exist", headers=_auth(token))
    assert missing.status_code == 404
