"""Admin user management (Phase 9): directory + search, create, edit (incl.
password reset), soft-ban/unban with login/token enforcement, hard delete, and
the self/last-admin lockout guards."""

from datetime import timedelta

from sqlalchemy import select

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


async def _add_links(user_id: str) -> None:
    async with SessionLocal() as session:
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


async def test_admin_email_change_vouches_for_the_new_address(client):
    """GHSA-42m4: the administrator vouches for an address they set, as at
    account creation — the account isn't stranded unverified (with verification
    off there'd be no way back, and trusted-email SSO would refuse it), and the
    old address's verification isn't what's carried over. Links mailed to the
    old address die, as on /change-email. A change of letter case alone is the
    same address and keeps both."""
    admin = await admin_token(client)
    token = await _register(client, "moved@example.com")
    user_id = (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]
    await _add_links(user_id)

    same = await client.patch(
        f"/api/users/{user_id}", json={"email": "Moved@example.com"}, headers=_auth(admin)
    )
    assert same.status_code == 200, same.text
    assert await _verified_at(user_id) is None
    assert len(await _links(user_id)) == 2

    moved = await client.patch(
        f"/api/users/{user_id}", json={"email": "elsewhere@example.com"}, headers=_auth(admin)
    )
    assert moved.status_code == 200, moved.text
    assert await _verified_at(user_id) is not None
    assert await _links(user_id) == []


async def test_kept_verification_link_still_works_after_a_case_only_admin_edit(
    client, monkeypatch
):
    """Links are bound to their address case-insensitively, like every other
    address comparison (§7.7): re-casing the address keeps the link, and the
    link still verifies."""
    import re

    from utils import mailer

    sent: list[tuple] = []

    async def _capture(to, subject, body):
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(mailer, "send_email", _capture)
    admin = await admin_token(client)
    enabled = await client.put(
        "/api/site-settings/operational",
        json={
            "registration_open": True,
            "email_verification_enabled": True,
            "smtp_host": "smtp.example.com",
        },
        headers=_auth(admin),
    )
    assert enabled.status_code == 200, enabled.text
    token = await _register(client, "recase@example.com")
    user_id = (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]
    link = re.search(r"token=([\w\-]+)", sent[0][2]).group(1)

    recased = await client.patch(
        f"/api/users/{user_id}", json={"email": "ReCase@example.com"}, headers=_auth(admin)
    )
    assert recased.status_code == 200, recased.text
    verify = await client.post("/api/auth/verify-email", json={"token": link})
    assert verify.status_code == 204, verify.text
    assert await _verified_at(user_id) is not None


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


async def _help_desk(client) -> str:
    from models.role import Role, RoleAssignment

    token = await _register(client, "desk@example.com")
    desk_id = (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]
    async with SessionLocal() as db:
        role = Role(name="Help desk", scope="global", permissions=["manage_users", "view_all_users"])
        db.add(role)
        await db.flush()
        db.add(RoleAssignment(user_id=desk_id, competition_id=None, role_id=role.id))
        await db.commit()
    return token


async def test_only_an_administrator_vouches_for_an_address(client):
    """GHSA-42m4: trusted-email SSO linking believes a verified address, so a
    narrower manage_users delegate setting one — at create, by CSV or by edit —
    leaves it unproven; only an Administrator's word verifies it."""
    await admin_token(client)
    desk = await _help_desk(client)

    created = await client.post(
        "/api/users",
        json={"email": "ceo@corp.example", "display_name": "ceo", "password": "password123"},
        headers=_auth(desk),
    )
    assert created.status_code == 201, created.text
    assert await _verified_at(created.json()["id"]) is None

    imported = await client.post(
        "/api/users/import",
        files={"file": ("u.csv", b"display_name,email,password\ncfo,cfo@corp.example,password123\n", "text/csv")},
        headers=_auth(desk),
    )
    assert imported.status_code in (200, 201), imported.text
    async with SessionLocal() as db:
        cfo = await db.scalar(select(User).where(User.display_name == "cfo"))
    assert cfo is not None and cfo.email_verified_at is None

    token = await _register(client, "player@example.com")
    player_id = (await client.get("/api/auth/me", headers=_auth(token))).json()["id"]
    async with SessionLocal() as db:
        (await db.get(User, player_id)).email_verified_at = utcnow()
        await db.commit()
    moved = await client.patch(
        f"/api/users/{player_id}", json={"email": "mine@desk.example"}, headers=_auth(desk)
    )
    assert moved.status_code == 200, moved.text
    assert await _verified_at(player_id) is None
