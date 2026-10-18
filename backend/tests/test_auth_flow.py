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


async def test_change_password_is_throttled(client):
    """GHSA-vv68: change-password is a password-taking endpoint, so it's rate
    limited (5/300s) like change-username/change-email — a stolen session can't
    brute-force the current password through it. The throttle fires BEFORE the
    password check (a correct guess on the 6th try still 429s), so it's not an
    oracle."""
    login = await client.post(
        "/api/auth/login",
        json={"email": DEFAULT_ADMIN_EMAIL, "password": DEFAULT_ADMIN_PASSWORD},
    )
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

    for _ in range(5):
        r = await client.post(
            "/api/auth/change-password",
            json={"current_password": "wrong", "new_password": "irrelevant-123"},
            headers=auth,
        )
        assert r.status_code == 400
    blocked = await client.post(
        "/api/auth/change-password",
        json={"current_password": DEFAULT_ADMIN_PASSWORD, "new_password": "irrelevant-123"},
        headers=auth,
    )
    assert blocked.status_code == 429


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


# --- self-service password reset (Phase 9, Group D) --------------------------


async def test_forgot_and_reset_password_flow(client, monkeypatch):
    import re

    from utils import mailer

    sent: list[tuple] = []

    async def _capture(to, subject, body):
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(mailer, "send_email", _capture)

    await _register(client, "forgetful@example.com", password="oldpassword1", name="Fp")
    old_refresh = client.cookies.get("refresh_token")
    assert old_refresh

    # Requesting a reset always 202s (even for an unknown address).
    assert (await client.post("/api/auth/forgot-password", json={"email": "forgetful@example.com"})).status_code == 204
    assert (await client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})).status_code == 204
    # Only the real account got an email; extract its token from the link.
    assert len(sent) == 1
    token = re.search(r"token=([\w\-]+)", sent[0][2]).group(1)

    # Reset with the token, then the new password works and the old one doesn't.
    assert (await client.post("/api/auth/reset-password", json={"token": token, "new_password": "brandnew1"})).status_code == 204
    # A reset ends every existing session.
    client.cookies.clear()
    assert (await client.post("/api/auth/refresh", cookies={"refresh_token": old_refresh})).status_code == 401
    assert (await client.post("/api/auth/login", json={"identifier": "forgetful@example.com", "password": "brandnew1"})).status_code == 200
    assert (await client.post("/api/auth/login", json={"identifier": "forgetful@example.com", "password": "oldpassword1"})).status_code == 401

    # The token is single-use — a replay is rejected.
    assert (await client.post("/api/auth/reset-password", json={"token": token, "new_password": "another1"})).status_code == 400


async def test_reset_password_rejects_bad_token(client):
    resp = await client.post("/api/auth/reset-password", json={"token": "garbage", "new_password": "whatever1"})
    assert resp.status_code == 400


async def test_forgot_password_matches_email_case_insensitively(client, monkeypatch):
    """Login/registration match email case-insensitively (§7.7); the reset flow
    must too, or a differently-cased address silently gets no email."""
    from utils import mailer

    sent: list[tuple] = []

    async def _capture(to, subject, body):
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(mailer, "send_email", _capture)
    await _register(client, "Mixed.Case@Example.com", password="oldpassword1", name="Mc")

    # Request with a different case — should still find the account and email it.
    resp = await client.post(
        "/api/auth/forgot-password", json={"email": "mixed.case@example.com"}
    )
    assert resp.status_code == 204
    assert len(sent) == 1


def _capture_mail(monkeypatch) -> list[tuple]:
    from utils import mailer

    sent: list[tuple] = []

    async def _capture(to, subject, body):
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(mailer, "send_email", _capture)
    return sent


async def test_reset_link_is_not_minted_for_an_address_the_account_left(
    client, monkeypatch
):
    """GHSA-42m4: the reset link is minted after forgot-password answers. An
    admin moving the account to another address in between must not leave the
    old mailbox holding a working link to it — nothing is minted or mailed."""
    from routers import auth as auth_router
    from models.password_reset import PasswordResetToken
    from tests.conftest import admin_token

    sent = _capture_mail(monkeypatch)
    admin = await admin_token(client)
    reg = await _register(client, "old@example.com", name="Mover")
    user_id = reg.json()["user"]["id"]
    real_session_local = auth_router.SessionLocal

    class _MovedFirst:
        """The minting session — opened only after the admin's change commits."""

        async def __aenter__(self):
            moved = await client.patch(
                f"/api/users/{user_id}",
                json={"email": "new@example.com"},
                headers={"Authorization": f"Bearer {admin}"},
            )
            assert moved.status_code == 200, moved.text
            self._inner = real_session_local()
            return await self._inner.__aenter__()

        async def __aexit__(self, *exc):
            return await self._inner.__aexit__(*exc)

    monkeypatch.setattr(auth_router, "SessionLocal", _MovedFirst)
    resp = await client.post("/api/auth/forgot-password", json={"email": "old@example.com"})
    assert resp.status_code == 204
    monkeypatch.setattr(auth_router, "SessionLocal", real_session_local)

    assert [m for m in sent if m[1] == "Reset your password"] == []
    async with SessionLocal() as session:
        assert (await session.scalars(select(PasswordResetToken))).all() == []


async def test_reset_link_only_works_while_the_account_holds_its_address(
    client, monkeypatch
):
    """GHSA-42m4: a reset link proves the address it was mailed to. If the
    account has moved to another address by the time the link is used — here,
    after a change whose token sweep ran before this link committed — the link
    resets nothing."""
    import re

    from sqlalchemy import update

    from models.user import User

    sent = _capture_mail(monkeypatch)
    reg = await _register(client, "old@example.com", password="oldpassword1", name="Mover")
    user_id = reg.json()["user"]["id"]
    await client.post("/api/auth/forgot-password", json={"email": "old@example.com"})
    link = re.search(r"token=([\w\-]+)", sent[0][2]).group(1)
    async with SessionLocal() as session:
        await session.execute(
            update(User).where(User.id == user_id).values(email="new@example.com")
        )
        await session.commit()

    resp = await client.post(
        "/api/auth/reset-password", json={"token": link, "new_password": "brandnew1"}
    )
    assert resp.status_code == 400, resp.text
    for password, expected in (("oldpassword1", 200), ("brandnew1", 401)):
        login = await client.post(
            "/api/auth/login", json={"identifier": "Mover", "password": password}
        )
        assert login.status_code == expected, password


async def test_reset_link_minted_before_links_carried_their_address_is_refused(
    client, monkeypatch
):
    """A reset token from before tokens recorded their address can't be tied
    to one, so it's refused (they expire within the hour anyway)."""
    import re

    from sqlalchemy import update

    from models.password_reset import PasswordResetToken

    sent = _capture_mail(monkeypatch)
    await _register(client, "legacy@example.com", password="oldpassword1", name="Legacy")
    await client.post("/api/auth/forgot-password", json={"email": "legacy@example.com"})
    link = re.search(r"token=([\w\-]+)", sent[0][2]).group(1)
    async with SessionLocal() as session:
        await session.execute(update(PasswordResetToken).values(email=None))
        await session.commit()

    resp = await client.post(
        "/api/auth/reset-password", json={"token": link, "new_password": "brandnew1"}
    )
    assert resp.status_code == 400, resp.text
    login = await client.post(
        "/api/auth/login", json={"identifier": "Legacy", "password": "oldpassword1"}
    )
    assert login.status_code == 200


async def test_refresh_token_reuse_revokes_the_family(client, monkeypatch):
    """GHSA-vv68 / RFC 9700 §4.14.2: replaying a revoked (already-rotated) refresh
    token is treated as theft — the whole login family is revoked, killing the
    live descendant chain, not just the replayed token. (Grace disabled so the
    immediate replay counts as reuse rather than a benign double-submit.)"""
    from routers import auth as auth_router

    monkeypatch.setattr(auth_router, "_REFRESH_REUSE_GRACE_SECONDS", -1)

    reg = await client.post(
        "/api/auth/register",
        json={"display_name": "reuse", "email": "reuse@example.com", "password": "password123"},
    )
    assert reg.status_code == 201
    token_a = client.cookies.get("refresh_token")
    assert token_a

    # Legit rotation A -> B; the client's cookie is now B.
    r1 = await client.post("/api/auth/refresh")
    assert r1.status_code == 200
    token_b = client.cookies.get("refresh_token")
    assert token_b and token_b != token_a

    # An attacker replays the revoked token A -> reuse detected -> family revoked.
    replay = await client.post("/api/auth/refresh", cookies={"refresh_token": token_a})
    assert replay.status_code == 401

    # The live chain B is now dead too — the whole family was revoked.
    r2 = await client.post("/api/auth/refresh")  # client still holds B
    assert r2.status_code == 401


async def test_pre_family_session_joins_a_family_when_rotated(client, monkeypatch):
    """GHSA-vv68: a session minted before reuse detection has no family. Its
    first rotation gives it one shared with the successor, so replaying the
    rotated-out token still revokes the live chain."""
    from models.user import RefreshSession
    from routers import auth as auth_router
    from auth.security import hash_refresh_token

    monkeypatch.setattr(auth_router, "_REFRESH_REUSE_GRACE_SECONDS", -1)
    reg = await client.post(
        "/api/auth/register",
        json={"display_name": "legacy", "email": "legacy@example.com", "password": "password123"},
    )
    assert reg.status_code == 201
    token_a = client.cookies.get("refresh_token")
    async with SessionLocal() as db:
        session = await db.scalar(
            select(RefreshSession).where(
                RefreshSession.token_hash == hash_refresh_token(token_a)
            )
        )
        session.family_id = None  # as if minted before the migration
        await db.commit()

    rotated = await client.post("/api/auth/refresh")
    assert rotated.status_code == 200
    replay = await client.post("/api/auth/refresh", cookies={"refresh_token": token_a})
    assert replay.status_code == 401
    chain = await client.post("/api/auth/refresh")  # the successor is dead too
    assert chain.status_code == 401


async def test_concurrent_refreshes_rotate_a_token_once(client):
    """GHSA-vv68: two refreshes presenting the same token at once get one
    successor between them, so the lineage can't fork into two live chains."""
    import asyncio

    reg = await client.post(
        "/api/auth/register",
        json={"display_name": "racer", "email": "racer@example.com", "password": "password123"},
    )
    assert reg.status_code == 201
    token = client.cookies.get("refresh_token")
    client.cookies.clear()
    results = await asyncio.gather(
        *(
            client.post("/api/auth/refresh", cookies={"refresh_token": token})
            for _ in range(4)
        )
    )
    assert sorted(r.status_code for r in results) == [200, 401, 401, 401], [
        (r.status_code, r.text) for r in results
    ]


async def test_password_checks_run_off_the_event_loop(client, monkeypatch):
    """GHSA-vv68: change-email and change-username verify the current password
    on the bounded hash pool, like change-password — argon2 inline would stall
    every request and socket on the worker for each guess."""
    import threading

    from auth import security

    threads: list[str] = []
    real_verify = security._password_hasher.verify

    def recording_verify(hashed, raw):
        threads.append(threading.current_thread().name)
        return real_verify(hashed, raw)

    monkeypatch.setattr(security._password_hasher, "verify", recording_verify)
    reg = await client.post(
        "/api/auth/register",
        json={"display_name": "looper", "email": "looper@example.com", "password": "password123"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    await client.post(
        "/api/auth/change-email",
        json={"new_email": "other@example.com", "current_password": "wrong-password"},
        headers=headers,
    )
    await client.post(
        "/api/auth/change-username",
        json={"new_display_name": "looper2", "current_password": "wrong-password"},
        headers=headers,
    )
    assert len(threads) >= 2, threads
    assert all(name.startswith("pwhash") for name in threads), threads
