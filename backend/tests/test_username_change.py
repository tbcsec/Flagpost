"""Self-service username (display-name) change: password re-auth, cooldown,
uniqueness, the user.renamed audit trail, and admin rename + bypass.

Username is the primary login handle (ADR-0015), so the guards mirror
change-email (current password required, per-request throttle) plus a
DB-backed cooldown that survives restarts.
"""

from datetime import timedelta

from sqlalchemy import select

from db import SessionLocal, utcnow
from models.audit_log import AuditLogEntry
from models.user import USERNAME_CHANGE_COOLDOWN, User
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, name: str, pw: str = "password123") -> tuple[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={"email": f"{name}@example.com", "password": pw, "display_name": name},
    )
    token = resp.json()["access_token"]
    me = await client.get("/api/auth/me", headers=_auth(token))
    return token, me.json()["id"]


async def _change(client, token: str, new_name: str, pw: str = "password123"):
    return await client.post(
        "/api/auth/change-username",
        json={"current_password": pw, "new_display_name": new_name},
        headers=_auth(token),
    )


async def _backdate_cooldown(user_id: str) -> None:
    """Pretend the last change was long enough ago that the cooldown has lapsed."""
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        user.username_changed_at = utcnow() - USERNAME_CHANGE_COOLDOWN - timedelta(days=1)
        await session.commit()


async def test_successful_change_and_login_by_new_name(client):
    token, user_id = await _register(client, "ada")

    me = await client.get("/api/auth/me", headers=_auth(token))
    assert me.json()["username_change_allowed_at"] is None  # never changed

    resp = await _change(client, token, "countess")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "countess"
    assert body["username_change_allowed_at"] is not None  # cooldown now armed

    # Login follows the new handle; the old one no longer resolves.
    ok = await client.post(
        "/api/auth/login",
        json={"identifier": "countess", "password": "password123"},
    )
    assert ok.status_code == 200
    gone = await client.post(
        "/api/auth/login",
        json={"identifier": "ada", "password": "password123"},
    )
    assert gone.status_code == 401


async def test_wrong_password_refused(client):
    token, _ = await _register(client, "grace")
    resp = await _change(client, token, "amazing", pw="wrong-password")
    assert resp.status_code == 400
    me = await client.get("/api/auth/me", headers=_auth(token))
    assert me.json()["display_name"] == "grace"  # unchanged


async def test_cooldown_blocks_a_second_change_then_lapses(client):
    token, user_id = await _register(client, "hopper")
    assert (await _change(client, token, "amazing")).status_code == 200

    # Immediately again → blocked by the cooldown.
    again = await _change(client, token, "amazing2")
    assert again.status_code == 409

    # Once the window lapses, a change goes through.
    await _backdate_cooldown(user_id)
    later = await _change(client, token, "amazing3")
    assert later.status_code == 200, later.text
    assert later.json()["display_name"] == "amazing3"


async def test_taken_name_refused_but_case_fix_allowed(client):
    await _register(client, "taken")
    token, _ = await _register(client, "mine")

    clash = await _change(client, token, "TAKEN")  # case-insensitively taken
    assert clash.status_code == 409

    # Fixing your own capitalisation is allowed (excluded from the uniqueness
    # check by self-id) and is a real change to the stored display name.
    fix = await _change(client, token, "Mine")
    assert fix.status_code == 200
    assert fix.json()["display_name"] == "Mine"


async def test_noop_same_name_refused(client):
    token, _ = await _register(client, "same")
    resp = await _change(client, token, "same")
    assert resp.status_code == 400


async def test_rate_limited_before_password_check(client):
    token, _ = await _register(client, "brute")
    # The limiter is hit before the password check (5/300s), so even wrong
    # guesses count — the 6th attempt is throttled rather than a 400.
    for _ in range(5):
        assert (await _change(client, token, "x", pw="nope")).status_code == 400
    assert (await _change(client, token, "x", pw="nope")).status_code == 429


async def test_self_change_audits_with_old_and_new(client):
    token, user_id = await _register(client, "before")
    await _change(client, token, "after")

    async with SessionLocal() as session:
        entry = (
            await session.execute(
                select(AuditLogEntry).where(AuditLogEntry.event_name == "user.renamed")
            )
        ).scalar_one()
    assert entry.payload["old_name"] == "before"
    assert entry.payload["new_name"] == "after"
    assert entry.payload["actor_user_id"] == user_id  # self-service


async def test_admin_rename_bypasses_cooldown_and_audits_actor(client):
    token, user_id = await _register(client, "rowdy")
    # User uses their one change, arming the cooldown.
    assert (await _change(client, token, "rowdy2")).status_code == 200

    admin = await admin_token(client)
    admin_id = (await client.get("/api/auth/me", headers=_auth(admin))).json()["id"]
    # Admin renames despite the user's active cooldown (moderation).
    resp = await client.patch(
        f"/api/users/{user_id}",
        json={"display_name": "clean-name"},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "clean-name"

    # The user still can't rename back — the admin action re-stamped the clock.
    blocked = await _change(client, token, "rowdy")
    assert blocked.status_code == 409

    async with SessionLocal() as session:
        entries = (
            await session.execute(
                select(AuditLogEntry).where(AuditLogEntry.event_name == "user.renamed")
            )
        ).scalars().all()
    admin_entry = next(e for e in entries if e.payload["actor_user_id"] == admin_id)
    assert admin_entry.payload["old_name"] == "rowdy2"
    assert admin_entry.payload["new_name"] == "clean-name"
