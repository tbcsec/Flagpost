"""Admin user management (Phase 9): directory + search, create, edit (incl.
password reset), soft-ban/unban with login/token enforcement, hard delete, and
the self/last-admin lockout guards."""

from datetime import timedelta

from sqlalchemy import select, update

from db import SessionLocal, utcnow
from models.email_verification import EmailVerificationToken
from models.password_reset import PasswordResetToken
from models.user import User
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


async def test_admin_create_without_email_and_display_name_unique(client):
    admin = await admin_token(client)
    # Email is optional — an admin can mint an account with just a username.
    resp = await client.post(
        "/api/users",
        json={"display_name": "Handle", "password": "s3cretpw!"},
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] is None

    # That user can sign in by username, and the display name is now taken
    # (case-insensitively).
    assert (
        await client.post(
            "/api/auth/login", json={"identifier": "handle", "password": "s3cretpw!"}
        )
    ).status_code == 200
    clash = await client.post(
        "/api/users",
        json={"display_name": "HANDLE", "password": "s3cretpw!"},
        headers=_auth(admin),
    )
    assert clash.status_code == 409
    assert "display name" in clash.json()["detail"].lower()


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


async def _stamp_verified_with_links(user_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(User).where(User.id == user_id).values(email_verified_at=utcnow())
        )
        for model, token_hash in (
            (EmailVerificationToken, "v" * 64),
            (PasswordResetToken, "r" * 64),
        ):
            session.add(
                model(
                    user_id=user_id,
                    token_hash=token_hash,
                    expires_at=utcnow() + timedelta(hours=1),
                )
            )
        await session.commit()


async def _verified_at(user_id: str):
    async with SessionLocal() as session:
        return (await session.get(User, user_id)).email_verified_at


async def _links(user_id: str) -> list:
    async with SessionLocal() as session:
        return [
            *(await session.scalars(
                select(EmailVerificationToken).where(EmailVerificationToken.user_id == user_id)
            )).all(),
            *(await session.scalars(
                select(PasswordResetToken).where(PasswordResetToken.user_id == user_id)
            )).all(),
        ]


async def test_admin_email_change_reopens_verification(client):
    """GHSA-42m4: an address an administrator types in is as unproven as one
    the user types — carrying the old verification over would let
    trusted-email SSO link it and the join gate admit it. Mirrors
    /change-email: the stamp clears and links mailed to the old address die. A
    change of letter case alone is the same address and keeps both."""
    admin = await admin_token(client)
    token = await _register(client, "moved@example.com")
    user_id = (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]
    await _stamp_verified_with_links(user_id)

    same = await client.patch(
        f"/api/users/{user_id}", json={"email": "Moved@example.com"}, headers=_auth(admin)
    )
    assert same.status_code == 200, same.text
    assert await _verified_at(user_id) is not None
    assert len(await _links(user_id)) == 2

    moved = await client.patch(
        f"/api/users/{user_id}", json={"email": "elsewhere@example.com"}, headers=_auth(admin)
    )
    assert moved.status_code == 200, moved.text
    assert await _verified_at(user_id) is None
    assert await _links(user_id) == []


async def test_admin_email_change_outlasts_a_verify_landing_meanwhile(client, monkeypatch):
    """GHSA-42m4: a /verify-email of the old address committing after the
    admin edit loaded the account (here, during its duplicate check) must not
    survive the change — the cleared stamp is written even though the loaded
    value was already empty."""
    import routers.users as users_router

    admin = await admin_token(client)
    token = await _register(client, "racer@example.com")
    user_id = (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]
    real_email_taken = users_router.email_taken

    async def _verify_lands_meanwhile(db, email, *, exclude_id=None):
        async with SessionLocal() as other:
            await other.execute(
                update(User).where(User.id == user_id).values(email_verified_at=utcnow())
            )
            await other.commit()
        return await real_email_taken(db, email, exclude_id=exclude_id)

    monkeypatch.setattr(users_router, "email_taken", _verify_lands_meanwhile)
    resp = await client.patch(
        f"/api/users/{user_id}", json={"email": "racer2@example.com"}, headers=_auth(admin)
    )
    assert resp.status_code == 200, resp.text
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
    assert user.email == "racer2@example.com"
    assert user.email_verified_at is None


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
