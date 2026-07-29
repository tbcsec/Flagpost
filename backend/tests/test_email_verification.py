"""Admin-toggleable email verification (issue #74).

An enabled gate makes email mandatory on public self-registration, mails a
confirmation link (mirroring the password-reset flow), and blocks the join
action — both the invite-code and public-competition paths, which share
``competitions._join`` — until the account is verified. Admin-created
accounts are stamped verified at creation and are exempt. Enabling the gate
itself requires SMTP to already be configured.
"""

import re

from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email=None, name="Verifier", password="password123"):
    payload = {"display_name": name, "password": password}
    if email is not None:
        payload["email"] = email
    return await client.post("/api/auth/register", json=payload)


async def _enable_verification(client, admin, *, smtp_host="smtp.example.com"):
    resp = await client.put(
        "/api/site-settings/operational",
        json={
            "registration_open": True,
            "email_verification_enabled": True,
            "smtp_host": smtp_host,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _mock_mailer(monkeypatch):
    from utils import mailer

    sent: list[tuple] = []

    async def _capture(to, subject, body):
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(mailer, "send_email", _capture)
    return sent


async def _make_competition(client, admin, *, visibility="public", **extra) -> dict:
    resp = await client.post(
        "/api/competitions",
        json={
            "name": extra.pop("name", "CTF"),
            "participation_mode": "individual",
            "visibility": visibility,
            **extra,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- enabling the gate ---------------------------------------------------------


async def test_enabling_requires_smtp_configured(client):
    admin = await admin_token(client)
    resp = await client.put(
        "/api/site-settings/operational",
        json={"registration_open": True, "email_verification_enabled": True},
        headers=_auth(admin),
    )
    assert resp.status_code == 400, resp.text
    assert "smtp" in resp.json()["detail"].lower()

    # Public read is unaffected — the setting never took.
    public = await client.get("/api/site-settings")
    assert public.json()["email_verification_enabled"] is False


async def test_enabling_succeeds_with_smtp_configured(client):
    admin = await admin_token(client)
    body = await _enable_verification(client, admin)
    assert body["email_verification_enabled"] is True

    public = await client.get("/api/site-settings")
    assert public.json()["email_verification_enabled"] is True
    assert public.json()["email_required"] is True


# --- registration ----------------------------------------------------------------


async def test_registration_requires_email_when_enabled(client):
    admin = await admin_token(client)
    await _enable_verification(client, admin)

    resp = await _register(client, email=None, name="NoEmail")
    assert resp.status_code == 400, resp.text


async def test_registration_sends_verification_email(client, monkeypatch):
    admin = await admin_token(client)
    await _enable_verification(client, admin)
    sent = _mock_mailer(monkeypatch)

    resp = await _register(client, email="fresh@example.com", name="Fresh")
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["email_verified_at"] is None
    assert len(sent) == 1
    assert "verify" in sent[0][1].lower()
    assert re.search(r"token=([\w\-]+)", sent[0][2]) is not None


async def test_registration_unaffected_when_disabled(client, monkeypatch):
    sent = _mock_mailer(monkeypatch)
    resp = await _register(client, email=None, name="Whoever")
    assert resp.status_code == 201, resp.text
    assert sent == []


# --- verify / resend --------------------------------------------------------------


async def test_verify_happy_path(client, monkeypatch):
    admin = await admin_token(client)
    await _enable_verification(client, admin)
    sent = _mock_mailer(monkeypatch)

    resp = await _register(client, email="verifyme@example.com", name="VerifyMe")
    token = re.search(r"token=([\w\-]+)", sent[0][2]).group(1)

    verify = await client.post("/api/auth/verify-email", json={"token": token})
    assert verify.status_code == 204, verify.text

    me = await client.get(
        "/api/auth/me", headers=_auth(resp.json()["access_token"])
    )
    assert me.json()["email_verified_at"] is not None

    # Single-use — a replay is rejected.
    replay = await client.post("/api/auth/verify-email", json={"token": token})
    assert replay.status_code == 400


async def test_verify_rejects_invalid_token(client):
    resp = await client.post("/api/auth/verify-email", json={"token": "garbage"})
    assert resp.status_code == 400


async def test_verify_rejects_expired_token(client, monkeypatch):
    from datetime import timedelta

    from sqlalchemy import select

    from db import SessionLocal, utcnow
    from models.email_verification import EmailVerificationToken

    admin = await admin_token(client)
    await _enable_verification(client, admin)
    sent = _mock_mailer(monkeypatch)
    await _register(client, email="expires@example.com", name="Expires")
    token = re.search(r"token=([\w\-]+)", sent[0][2]).group(1)

    # Backdate the token's expiry so it's already elapsed.
    async with SessionLocal() as session:
        row = (
            await session.execute(select(EmailVerificationToken))
        ).scalars().first()
        row.expires_at = utcnow() - timedelta(hours=1)
        await session.commit()

    resp = await client.post("/api/auth/verify-email", json={"token": token})
    assert resp.status_code == 400


async def test_resend_rate_limited_and_gated(client, monkeypatch):
    admin = await admin_token(client)
    await _enable_verification(client, admin)
    sent = _mock_mailer(monkeypatch)

    resp = await _register(client, email="resend@example.com", name="Resend")
    token = resp.json()["access_token"]
    assert len(sent) == 1

    ok = await client.post("/api/auth/resend-verification", headers=_auth(token))
    assert ok.status_code == 204, ok.text
    assert len(sent) == 2

    # Second call within the 60s window is throttled.
    throttled = await client.post(
        "/api/auth/resend-verification", headers=_auth(token)
    )
    assert throttled.status_code == 429


async def test_resend_rejects_when_already_verified(client, monkeypatch):
    admin = await admin_token(client)
    await _enable_verification(client, admin)
    sent = _mock_mailer(monkeypatch)

    resp = await _register(client, email="already@example.com", name="Already")
    token = re.search(r"token=([\w\-]+)", sent[0][2]).group(1)
    await client.post("/api/auth/verify-email", json={"token": token})

    resend = await client.post(
        "/api/auth/resend-verification", headers=_auth(resp.json()["access_token"])
    )
    assert resend.status_code == 400


async def test_resend_rejects_when_feature_disabled(client):
    resp = await _register(client, email="disabled@example.com", name="Disabled")
    resend = await client.post(
        "/api/auth/resend-verification",
        headers=_auth(resp.json()["access_token"]),
    )
    assert resend.status_code == 400


# --- join gate ---------------------------------------------------------------------


async def test_join_blocked_until_verified_then_allowed(client, monkeypatch):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    await _enable_verification(client, admin)
    sent = _mock_mailer(monkeypatch)

    resp = await _register(client, email="joiner@example.com", name="Joiner")
    token = resp.json()["access_token"]

    blocked = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert blocked.status_code == 403, blocked.text

    verify_token = re.search(r"token=([\w\-]+)", sent[0][2]).group(1)
    await client.post("/api/auth/verify-email", json={"token": verify_token})

    allowed = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert allowed.status_code == 200, allowed.text


async def test_invite_code_join_blocked_until_verified(client, monkeypatch):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin, visibility="private")
    await _enable_verification(client, admin)
    sent = _mock_mailer(monkeypatch)

    resp = await _register(client, email="coder@example.com", name="Coder")
    token = resp.json()["access_token"]

    blocked = await client.post(
        "/api/competitions/join",
        json={"invite_code": comp["invite_code"]},
        headers=_auth(token),
    )
    assert blocked.status_code == 403, blocked.text

    verify_token = re.search(r"token=([\w\-]+)", sent[0][2]).group(1)
    await client.post("/api/auth/verify-email", json={"token": verify_token})

    allowed = await client.post(
        "/api/competitions/join",
        json={"invite_code": comp["invite_code"]},
        headers=_auth(token),
    )
    assert allowed.status_code == 200, allowed.text


async def test_join_not_gated_mid_competition_once_already_joined(client, monkeypatch):
    """Turning the setting on after a competitor already joined must not
    retroactively block anything else they do — the gate is join-only."""
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    resp = await _register(client, email="early@example.com", name="Early")
    token = resp.json()["access_token"]

    join = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert join.status_code == 200, join.text

    await _enable_verification(client, admin)
    _mock_mailer(monkeypatch)

    # Re-joining (idempotent) still succeeds — already a member, never re-gated.
    rejoin = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(token)
    )
    assert rejoin.status_code == 200, rejoin.text


async def test_admin_created_accounts_exempt_from_join_gate(client):
    admin = await admin_token(client)
    comp = await _make_competition(client, admin)
    await _enable_verification(client, admin)

    created = await client.post(
        "/api/users",
        json={
            "display_name": "MintedByAdmin",
            "password": "password123",
            "email": "minted@example.com",
        },
        headers=_auth(admin),
    )
    assert created.status_code == 201, created.text

    login = await client.post(
        "/api/auth/login",
        json={"identifier": "MintedByAdmin", "password": "password123"},
    )
    assert login.status_code == 200, login.text

    join = await client.post(
        f"/api/competitions/{comp['id']}/join", headers=_auth(login.json()["access_token"])
    )
    assert join.status_code == 200, join.text
