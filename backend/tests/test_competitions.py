"""Competition endpoints: RBAC enforcement + event emission (§6, §7.6)."""

from sqlalchemy import select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from tests.conftest import admin_token


async def _register(client, email, name="User") -> str:
    """Register a plain user (Participant-level — no roles) and return a token."""
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": name},
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_admin_can_create_competition_and_event_is_emitted(client):
    token = await admin_token(client)

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
    assert entry.user_id is not None  # the seeded admin


async def test_participant_cannot_create_competition(client):
    # A freshly registered user has no role assignment -> Participant-level.
    token = await _register(client, "participant@example.com", "Player")

    resp = await client.post(
        "/api/competitions",
        json={"name": "Nope"},
        headers=_auth(token),
    )
    assert resp.status_code == 403


async def test_create_defaults_and_roundtrips_management_fields(client):
    token = await admin_token(client)
    resp = await client.post(
        "/api/competitions",
        json={
            "name": "Winter CTF",
            "visibility": "public",
            "registration_opens_at": "2026-01-01T00:00:00Z",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["visibility"] == "public"
    assert body["registration_opens_at"] is not None
    # Unspecified management fields fall back to their defaults.
    assert body["participation_mode"] == "team"


async def test_admin_can_update_competition_and_event_is_emitted(client):
    token = await admin_token(client)
    created = (
        await client.post(
            "/api/competitions", json={"name": "Draft"}, headers=_auth(token)
        )
    ).json()
    assert created["visibility"] == "private"  # default

    patched = await client.patch(
        f"/api/competitions/{created['id']}",
        json={"name": "Published", "visibility": "public"},
        headers=_auth(token),
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["name"] == "Published"
    assert body["visibility"] == "public"

    async with SessionLocal() as session:
        entry = (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "competition.updated"
                )
            )
        ).scalar_one()
    assert entry.competition_id == created["id"]
    assert entry.payload["changed_fields"] == ["name", "visibility"]


async def test_participant_cannot_update_competition(client):
    admin = await admin_token(client)
    created = (
        await client.post(
            "/api/competitions", json={"name": "Locked"}, headers=_auth(admin)
        )
    ).json()

    player = await _register(client, "editor-wannabe@example.com")
    resp = await client.patch(
        f"/api/competitions/{created['id']}",
        json={"name": "Hijacked"},
        headers=_auth(player),
    )
    assert resp.status_code == 403


async def test_update_missing_competition_is_404(client):
    token = await admin_token(client)
    resp = await client.patch(
        "/api/competitions/does-not-exist",
        json={"name": "Ghost"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


async def test_create_requires_authentication(client):
    resp = await client.post("/api/competitions", json={"name": "Anon"})
    assert resp.status_code == 401


async def test_list_and_get_competition(client):
    token = await admin_token(client)
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
