"""End-to-end auth flow + first-user bootstrap (§7.7, ADR-0003)."""

from sqlalchemy import select

from auth.deps import user_has_permission
from db import SessionLocal
from models.audit_log import AuditLogEntry


async def _register(client, email, password="password123", name="Test User"):
    return await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": name},
    )


async def test_register_login_me_refresh_logout(client):
    # Register (first user) -> 201 with an access token + user body.
    resp = await _register(client, "admin@example.com", name="Admin")
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "admin@example.com"
    token = body["access_token"]

    # The refresh token is an httpOnly cookie, never in the body.
    assert "refresh_token" not in body
    set_cookie = " ".join(resp.headers.get_list("set-cookie")).lower()
    assert "refresh_token=" in set_cookie
    assert "httponly" in set_cookie

    # /me with the bearer token returns the current user.
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"

    # Refresh rotates and returns a new access token (cookie auto-sent by client).
    refreshed = await client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]

    # Logout revokes; a subsequent refresh is rejected.
    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 204
    after = await client.post("/api/auth/refresh")
    assert after.status_code == 401


async def test_me_requires_authentication(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_duplicate_email_rejected(client):
    await _register(client, "dup@example.com")
    again = await _register(client, "dup@example.com")
    assert again.status_code == 409


async def test_login_wrong_password_rejected(client):
    await _register(client, "user@example.com", password="correct-horse")
    resp = await client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "wrong"},
    )
    assert resp.status_code == 401


async def test_first_user_is_admin_second_is_participant(client):
    first = await _register(client, "first@example.com")
    second = await _register(client, "second@example.com")
    first_id = first.json()["user"]["id"]
    second_id = second.json()["user"]["id"]

    async with SessionLocal() as session:
        # The first user holds a global Administrator assignment -> can create
        # competitions anywhere; the second holds nothing above Participant.
        assert await user_has_permission(
            session, first_id, "create_competition", None
        )
        assert not await user_has_permission(
            session, second_id, "create_competition", None
        )


async def test_registration_emits_user_registered_event(client):
    await _register(client, "evented@example.com")
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "user.registered"
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].payload["email"] == "evented@example.com"
