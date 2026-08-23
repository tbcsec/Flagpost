"""Self-service add / change / clear email (issue #106).

Own-user endpoint gated on the current password. Covers the owner's decisions:
a change re-opens verification, clearing is refused while verification is on,
the #56 domain allowlist applies here too, and outstanding reset/verification
tokens die on any actual change.
"""

from sqlalchemy import select

from db import SessionLocal
from models.email_verification import EmailVerificationToken
from models.password_reset import PasswordResetToken
from models.user import User
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _mock_mailer(monkeypatch):
    from utils import mailer

    sent: list[tuple] = []

    async def _capture(to, subject, body):
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(mailer, "send_email", _capture)
    return sent


async def _register(client, email=None, name="Ada", password="password123"):
    payload = {"display_name": name, "password": password}
    if email is not None:
        payload["email"] = email
    resp = await client.post("/api/auth/register", json=payload)
    return resp.json()["access_token"], resp.json()["user"]["id"]


async def _site(client, admin, **fields):
    resp = await client.put(
        "/api/site-settings/operational",
        json={"registration_open": True, **fields},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text


async def _change(client, token, password="password123", new_email="new@example.com"):
    return await client.post(
        "/api/auth/change-email",
        json={"current_password": password, "new_email": new_email},
        headers=_auth(token),
    )


async def test_sets_an_address_on_an_email_less_account(client):
    """The stranded-account case from the issue: registered with no email."""
    token, user_id = await _register(client)
    resp = await _change(client, token, new_email="ada@example.com")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == "ada@example.com"
    assert body["id"] == user_id
    # Returns the shared UserOut shape, so the client can drop it into the
    # auth store unmapped.
    assert set(body) == {
        "id",
        "email",
        "display_name",
        "created_at",
        "email_verified_at",
        "avatar_updated_at",
        "username_change_allowed_at",
    }


async def test_wrong_password_refused(client):
    token, _ = await _register(client, email="ada@example.com")
    resp = await _change(client, token, password="not-my-password")
    assert resp.status_code == 400

    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.display_name == "Ada"))
    assert user.email == "ada@example.com"  # unchanged


async def test_change_clears_verification_and_resends(client, monkeypatch):
    """Verifying a real address then swapping to another must not carry the
    verified flag across — that would be a trivial bypass of the #74 gate."""
    sent = _mock_mailer(monkeypatch)
    admin = await admin_token(client)
    await _site(client, admin, email_verification_enabled=True, smtp_host="smtp.example.com")

    token, user_id = await _register(client, email="old@example.com")
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        user.email_verified_at = user.created_at  # pretend it was verified
        await session.commit()

    sent.clear()
    resp = await _change(client, token, new_email="new@example.com")
    assert resp.status_code == 200, resp.text
    assert resp.json()["email_verified_at"] is None

    # A fresh verification mail goes to the new address...
    assert any("new@example.com" in to for to, _, _ in sent)
    # ...and the previous address is warned about the change.
    warned = [s for s in sent if "old@example.com" in s[0]]
    assert warned and "changed" in warned[0][1].lower()


async def test_clearing_refused_while_verification_required(client, monkeypatch):
    _mock_mailer(monkeypatch)
    admin = await admin_token(client)
    await _site(client, admin, email_verification_enabled=True, smtp_host="smtp.example.com")
    token, _ = await _register(client, email="ada@example.com")

    resp = await _change(client, token, new_email=None)
    assert resp.status_code == 400
    assert "can't be removed" in resp.json()["detail"]


async def test_clearing_allowed_when_verification_off(client):
    token, user_id = await _register(client, email="ada@example.com")
    resp = await _change(client, token, new_email=None)

    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] is None
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
    assert user.email is None and user.email_verified_at is None


async def test_domain_allowlist_applies_to_self_service_change(client):
    """#56's allowlist governs registration; the owner's call is that it governs
    this too — otherwise you register on an allowed domain then hop straight off
    it."""
    admin = await admin_token(client)
    await _site(
        client, admin,
        email_domain_allowlist_enabled=True,
        allowed_email_domains=["allowed.edu"],
    )
    token, _ = await _register(client, email="ada@allowed.edu")

    denied = await _change(client, token, new_email="ada@elsewhere.com")
    assert denied.status_code == 403

    ok = await _change(client, token, new_email="ada@mail.allowed.edu")  # subdomain
    assert ok.status_code == 200, ok.text


async def test_duplicate_address_refused_case_insensitively(client):
    await _register(client, email="taken@example.com", name="First")
    token, _ = await _register(client, email="ada@example.com", name="Second")

    resp = await _change(client, token, new_email="TAKEN@example.com")
    assert resp.status_code == 409


async def test_reset_and_verification_tokens_dropped_on_change(client, monkeypatch):
    """A reset link already sitting in the old inbox must not survive the switch."""
    _mock_mailer(monkeypatch)
    token, user_id = await _register(client, email="old@example.com")
    await client.post("/api/auth/forgot-password", json={"email": "old@example.com"})

    async with SessionLocal() as session:
        before = (await session.scalars(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user_id)
        )).all()
    assert len(before) == 1

    assert (await _change(client, token, new_email="new@example.com")).status_code == 200

    async with SessionLocal() as session:
        resets = (await session.scalars(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user_id)
        )).all()
        verifications = (await session.scalars(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user_id
            )
        )).all()
    assert resets == []
    assert verifications == []  # verification is off, so none was re-minted


async def test_same_address_is_a_noop(client, monkeypatch):
    """Resubmitting the current address must not nuke live reset links or
    mail anyone — /resend-verification is the resend path."""
    sent = _mock_mailer(monkeypatch)
    token, user_id = await _register(client, email="ada@example.com")
    await client.post("/api/auth/forgot-password", json={"email": "ada@example.com"})
    sent.clear()

    resp = await _change(client, token, new_email="ADA@example.com")  # same, recased
    assert resp.status_code == 200
    assert resp.json()["email"] == "ada@example.com"  # original casing kept

    async with SessionLocal() as session:
        resets = (await session.scalars(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user_id)
        )).all()
    assert len(resets) == 1, "a no-op must not invalidate a live reset token"
    assert sent == [], "a no-op must not notify anyone"


async def test_sessions_survive_the_change(client):
    """Unlike change-password, an email change doesn't log you out (GitHub /
    GitLab draw the line the same way) — the access token keeps working."""
    token, _ = await _register(client, email="ada@example.com")
    assert (await _change(client, token, new_email="new@example.com")).status_code == 200

    me = await client.get("/api/auth/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json()["email"] == "new@example.com"


async def test_rate_limited(client):
    """The endpoint takes an arbitrary password guess, so it must not be an
    unthrottled brute-force oracle for a stolen session."""
    token, _ = await _register(client, email="ada@example.com")
    codes = [
        (await _change(client, token, password="wrong", new_email="x@example.com")).status_code
        for _ in range(7)
    ]
    assert 429 in codes, codes
    # The limit bites on attempts, not just successes.
    assert codes.count(400) <= 5


async def test_broken_smtp_does_not_fail_a_completed_change(client, monkeypatch):
    """A dead mail server must not turn a change that already committed into a
    500. send_email no-ops only when SMTP is *unconfigured*; a configured but
    unreachable host raises, and that used to propagate — losing the response
    and the user.updated event for a change the database had already accepted."""
    from utils import mailer

    async def _explode(to, subject, body):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(mailer, "send_email", _explode)

    token, user_id = await _register(client, email="old@example.com")
    resp = await _change(client, token, new_email="new@example.com")

    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "new@example.com"
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
    assert user.email == "new@example.com"


async def test_emits_user_updated(client):
    from models.audit_log import AuditLogEntry

    token, user_id = await _register(client, email="ada@example.com")
    await _change(client, token, new_email="new@example.com")

    async with SessionLocal() as session:
        events = (await session.scalars(
            select(AuditLogEntry.event_name).where(
                AuditLogEntry.event_name == "user.updated"
            )
        )).all()
    assert "user.updated" in events
