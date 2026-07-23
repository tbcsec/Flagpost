"""End-to-end auth flow, seeded admin, and password change (§7.7, ADR-0003/0010)."""

from sqlalchemy import select

from auth.deps import user_has_permission
from auth.seed import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD
from db import SessionLocal
from models.audit_log import AuditLogEntry


async def _register(client, email, password="password123", name="Test User"):
    return await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": name},
    )


async def test_register_login_me_refresh_logout(client):
    # Register -> 201 with an access token + user body.
    resp = await _register(client, "user@example.com", name="User")
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "user@example.com"
    token = body["access_token"]

    # The refresh token is an httpOnly cookie, never in the body.
    assert "refresh_token" not in body
    set_cookie = " ".join(resp.headers.get_list("set-cookie")).lower()
    assert "refresh_token=" in set_cookie
    assert "httponly" in set_cookie

    # /me with the bearer token returns the current user.
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"

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
    await _register(client, "dup@example.com", name="First")
    # Distinct display name, same email → the *email* uniqueness fires.
    again = await _register(client, "dup@example.com", name="Second")
    assert again.status_code == 409
    assert "email" in again.json()["detail"].lower()


async def test_duplicate_display_name_rejected_case_insensitive(client):
    assert (await _register(client, "a@example.com", name="Alice")).status_code == 201
    # Different email, same display name in different case → rejected (the display
    # name is the login identifier, unique case-insensitively).
    clash = await _register(client, "b@example.com", name="alice")
    assert clash.status_code == 409
    assert "display name" in clash.json()["detail"].lower()


async def test_register_without_email_then_login_by_username(client):
    # Email is optional now — register with only a username + password.
    resp = await client.post(
        "/api/auth/register",
        json={"display_name": "NoEmailNed", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["email"] is None

    # Log in by the display name (username).
    login = await client.post(
        "/api/auth/login",
        json={"identifier": "NoEmailNed", "password": "password123"},
    )
    assert login.status_code == 200


async def test_login_accepts_username_or_email_case_insensitively(client):
    await _register(client, "casey@example.com", name="CaseY")
    for identifier in ("CaseY", "casey", "CASEY@EXAMPLE.COM", "casey@example.com"):
        resp = await client.post(
            "/api/auth/login",
            json={"identifier": identifier, "password": "password123"},
        )
        assert resp.status_code == 200, (identifier, resp.text)


async def test_login_wrong_password_rejected(client):
    await _register(client, "user@example.com", password="correct-horse")
    resp = await client.post(
        "/api/auth/login",
        json={"email": "user@example.com", "password": "wrong"},
    )
    assert resp.status_code == 401


async def test_registered_user_has_no_elevated_permission(client):
    # Public registration never grants above Participant (ADR-0010) — a fresh
    # user holds no role assignment and so no global permission.
    resp = await _register(client, "plain@example.com")
    user_id = resp.json()["user"]["id"]
    async with SessionLocal() as session:
        assert not await user_has_permission(
            session, user_id, "create_competition", None
        )


async def test_seeded_admin_can_log_in_and_is_administrator(client):
    # The seeded default admin (fixture) logs in with the default credentials
    # and holds the global create_competition permission.
    resp = await client.post(
        "/api/auth/login",
        json={"email": DEFAULT_ADMIN_EMAIL, "password": DEFAULT_ADMIN_PASSWORD},
    )
    assert resp.status_code == 200
    admin_id = resp.json()["user"]["id"]
    async with SessionLocal() as session:
        assert await user_has_permission(
            session, admin_id, "create_competition", None
        )


async def test_change_password_updates_credential_and_revokes_sessions(client):
    login = await client.post(
        "/api/auth/login",
        json={"email": DEFAULT_ADMIN_EMAIL, "password": DEFAULT_ADMIN_PASSWORD},
    )
    token = login.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    # Wrong current password is rejected.
    bad = await client.post(
        "/api/auth/change-password",
        json={"current_password": "nope", "new_password": "brand-new-pass"},
        headers=auth,
    )
    assert bad.status_code == 400

    ok = await client.post(
        "/api/auth/change-password",
        json={
            "current_password": DEFAULT_ADMIN_PASSWORD,
            "new_password": "brand-new-pass",
        },
        headers=auth,
    )
    assert ok.status_code == 204

    # The refresh session issued at login was revoked by the change — check this
    # before re-logging in, which would set a fresh (valid) cookie.
    refreshed = await client.post("/api/auth/refresh")
    assert refreshed.status_code == 401

    # Old password no longer works; new one does.
    old = await client.post(
        "/api/auth/login",
        json={"email": DEFAULT_ADMIN_EMAIL, "password": DEFAULT_ADMIN_PASSWORD},
    )
    assert old.status_code == 401
    new = await client.post(
        "/api/auth/login",
        json={"email": DEFAULT_ADMIN_EMAIL, "password": "brand-new-pass"},
    )
    assert new.status_code == 200


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
