"""Admin user management (Phase 9): directory + search, create, edit (incl.
password reset), soft-ban/unban with login/token enforcement, hard delete, and
the self/last-admin lockout guards."""

from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str, pw: str = "password123") -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": pw, "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def test_list_and_search(client):
    admin = await admin_token(client)
    await _register(client, "ada@example.com")
    await _register(client, "bob@example.com")

    users = (await client.get("/api/users", headers=_auth(admin))).json()
    by_email = {u["email"]: u for u in users}
    assert "admin@example.com" in by_email
    assert by_email["admin@example.com"]["is_administrator"] is True
    assert by_email["ada@example.com"]["is_administrator"] is False
    assert by_email["ada@example.com"]["is_active"] is True

    # Search matches email/display name, case-insensitive.
    found = (await client.get("/api/users?q=ADA", headers=_auth(admin))).json()
    assert [u["email"] for u in found] == ["ada@example.com"]


async def test_directory_requires_permission(client):
    token = await _register(client, "nosy@example.com")  # no global role
    resp = await client.get("/api/users", headers=_auth(token))
    assert resp.status_code == 403


async def test_create_user_then_login(client):
    admin = await admin_token(client)
    resp = await client.post(
        "/api/users",
        json={"email": "new@example.com", "display_name": "New", "password": "s3cretpw!"},
        headers=_auth(admin),
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "new@example.com"

    # The created account can sign in with the initial password.
    login = await client.post(
        "/api/auth/login", json={"email": "new@example.com", "password": "s3cretpw!"}
    )
    assert login.status_code == 200

    # Duplicate email is rejected.
    dup = await client.post(
        "/api/users",
        json={"email": "new@example.com", "display_name": "Dup", "password": "s3cretpw!"},
        headers=_auth(admin),
    )
    assert dup.status_code == 409


async def test_edit_user_including_password(client):
    admin = await admin_token(client)
    token = await _register(client, "edit@example.com", "password123")
    me = (await client.get("/api/auth/me", headers=_auth(token))).json()

    resp = await client.patch(
        f"/api/users/{me['id']}",
        json={"display_name": "Renamed", "password": "brandNewpw!"},
        headers=_auth(admin),
    )
    assert resp.status_code == 200 and resp.json()["display_name"] == "Renamed"

    # New password works; old one doesn't.
    assert (
        await client.post(
            "/api/auth/login",
            json={"email": "edit@example.com", "password": "brandNewpw!"},
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/auth/login",
            json={"email": "edit@example.com", "password": "password123"},
        )
    ).status_code == 401


async def test_ban_blocks_login_and_token_then_unban_restores(client):
    admin = await admin_token(client)
    token = await _register(client, "banme@example.com")
    me = (await client.get("/api/auth/me", headers=_auth(token))).json()

    ban = await client.post(f"/api/users/{me['id']}/ban", headers=_auth(admin))
    assert ban.status_code == 200 and ban.json()["is_active"] is False

    # Existing access token is now rejected, and login is refused.
    assert (await client.get("/api/auth/me", headers=_auth(token))).status_code == 401
    assert (
        await client.post(
            "/api/auth/login",
            json={"email": "banme@example.com", "password": "password123"},
        )
    ).status_code == 403

    # Unban restores access.
    await client.post(f"/api/users/{me['id']}/unban", headers=_auth(admin))
    assert (
        await client.post(
            "/api/auth/login",
            json={"email": "banme@example.com", "password": "password123"},
        )
    ).status_code == 200


async def test_cannot_ban_self_or_last_admin(client):
    admin = await admin_token(client)
    me = (await client.get("/api/auth/me", headers=_auth(admin))).json()
    # The seeded admin is the only administrator — self-ban and last-admin guards
    # both fire (self check first).
    resp = await client.post(f"/api/users/{me['id']}/ban", headers=_auth(admin))
    assert resp.status_code == 409


async def test_delete_user_and_guards(client):
    admin = await admin_token(client)
    token = await _register(client, "gone@example.com")
    me = (await client.get("/api/auth/me", headers=_auth(token))).json()

    resp = await client.delete(f"/api/users/{me['id']}", headers=_auth(admin))
    assert resp.status_code == 204
    users = (await client.get("/api/users", headers=_auth(admin))).json()
    assert "gone@example.com" not in {u["email"] for u in users}

    # Can't delete yourself (and the seeded admin is also the last admin).
    admin_me = (await client.get("/api/auth/me", headers=_auth(admin))).json()
    resp = await client.delete(f"/api/users/{admin_me['id']}", headers=_auth(admin))
    assert resp.status_code == 409

    # Manage requires the permission.
    other = await _register(client, "other@example.com")
    resp = await client.delete(f"/api/users/{admin_me['id']}", headers=_auth(other))
    assert resp.status_code == 403
