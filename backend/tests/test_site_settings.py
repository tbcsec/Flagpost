"""Site-wide settings (ARCHITECTURE.md §9): public read, admin-gated update,
strict validation, and the site.settings_updated event."""

from sqlalchemy import select

from models.audit_log import AuditLogEntry
from models.site_settings import DEFAULT_ACCENT, DEFAULT_PALETTE, DEFAULT_PLATFORM_NAME
from tests.conftest import admin_token


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email: str) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def test_public_read_returns_defaults_without_auth(client):
    resp = await client.get("/api/site-settings")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "platform_name": DEFAULT_PLATFORM_NAME,
        "default_palette": DEFAULT_PALETTE,
        "accent": DEFAULT_ACCENT,
        "registration_open": True,
        "logo_url": None,
        "show_wordmark": True,
        "demo_mode": False,
        "archive_auto_delete": True,
        "archive_retention_days": 30,
        "email_required": False,
        "email_verification_enabled": False,
    }
    # Public shape only — no internal fields leak.
    assert "updated_at" not in body
    assert "smtp_host" not in body
    assert "logo_data" not in body
    assert "allowed_email_domains" not in body


async def test_admin_update_round_trips(client):
    admin = await admin_token(client)
    resp = await client.put(
        "/api/site-settings",
        json={"platform_name": "ACME CTF", "default_palette": "eclipse", "accent": "#A855F7"},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["platform_name"] == "ACME CTF"
    assert "updated_at" in resp.json()  # admin shape carries it

    # The public read now reflects the change.
    public = (await client.get("/api/site-settings")).json()
    assert public == {
        "platform_name": "ACME CTF",
        "default_palette": "eclipse",
        "accent": "#A855F7",
        "registration_open": True,
        "logo_url": None,
        "show_wordmark": True,
        "demo_mode": False,
        "archive_auto_delete": True,
        "archive_retention_days": 30,
        "email_required": False,
        "email_verification_enabled": False,
    }


async def test_update_requires_authentication(client):
    resp = await client.put(
        "/api/site-settings",
        json={"platform_name": "X", "default_palette": "harbor", "accent": "signal"},
    )
    assert resp.status_code == 401


async def test_update_requires_manage_site_settings(client):
    # A plain registered user has no global role → no manage_site_settings.
    token = await _register(client, "nobody@example.com")
    resp = await client.put(
        "/api/site-settings",
        json={"platform_name": "X", "default_palette": "harbor", "accent": "signal"},
        headers=_auth(token),
    )
    assert resp.status_code == 403


async def test_update_rejects_malformed_theme_values(client):
    admin = await admin_token(client)
    # A would-be CSS/attribute injection in either field is rejected (422).
    for bad in (
        {"platform_name": "X", "default_palette": "red; }", "accent": "signal"},
        {"platform_name": "X", "default_palette": "harbor", "accent": "url(evil)"},
        {"platform_name": "X", "default_palette": "harbor", "accent": "#12"},
        {"platform_name": "", "default_palette": "harbor", "accent": "signal"},
    ):
        resp = await client.put("/api/site-settings", json=bad, headers=_auth(admin))
        assert resp.status_code == 422, (bad, resp.text)


async def test_update_emits_settings_updated_event(client):
    admin = await admin_token(client)
    await client.put(
        "/api/site-settings",
        json={"platform_name": "Evented", "default_palette": "harbor", "accent": "azure"},
        headers=_auth(admin),
    )
    from db import SessionLocal

    async with SessionLocal() as session:
        events = (
            await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "site.settings_updated"
                )
            )
        ).scalars().all()
    assert len(events) == 1
    assert events[0].payload["accent"] == "azure"
    assert events[0].user_id is not None  # actor lifted for the audit log


# --- Operational settings (Phase 9): registration policy + SMTP ---


async def _register_resp(client, email: str):
    return await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )


async def test_operational_requires_permission(client):
    resp = await client.get("/api/site-settings/operational")
    assert resp.status_code in (401, 403)
    token = (await _register_resp(client, "nobody@example.com")).json()["access_token"]
    resp = await client.get(
        "/api/site-settings/operational", headers=_auth(token)
    )
    assert resp.status_code == 403


async def test_smtp_round_trips_password_write_only(client):
    admin = await admin_token(client)
    resp = await client.put(
        "/api/site-settings/operational",
        json={
            "registration_open": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "smtp_username": "postmaster",
            "smtp_from": "ctf@example.com",
            "smtp_starttls": False,
            "smtp_password": "s3cret",
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["smtp_host"] == "smtp.example.com"
    assert body["smtp_port"] == 465
    assert body["smtp_password_set"] is True
    assert "smtp_password" not in body  # never serialized back

    # Re-saving without a password keeps the stored one.
    resp = await client.put(
        "/api/site-settings/operational",
        json={
            "registration_open": True,
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "smtp_from": "ctf@example.com",
            "smtp_starttls": False,
        },
        headers=_auth(admin),
    )
    assert resp.json()["smtp_password_set"] is True


async def test_smtp_password_is_encrypted_at_rest(client):
    """ADR-0020 / #109: retrievable, so encrypted (not hashed) — but the raw
    column must not hold the plaintext."""
    from sqlalchemy import text

    from db import SessionLocal

    admin = await admin_token(client)
    resp = await client.put(
        "/api/site-settings/operational",
        json={
            "registration_open": True,
            "smtp_host": "smtp.example.com",
            "smtp_from": "ctf@example.com",
            "smtp_password": "super-secret-pw",
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 200

    # Raw SQL on purpose: reading through the ORM would run the EncryptedString
    # decrypt and hand back the plaintext, making this assertion meaningless.
    async with SessionLocal() as db:
        raw = (
            await db.execute(text("SELECT smtp_password FROM site_settings"))
        ).scalar_one()
    assert raw is not None
    assert "super-secret-pw" not in raw
    assert raw.startswith("gAAAAA"), "should be a Fernet token"

    # ...and it decrypts transparently through the ORM, so the mailer gets the
    # real password back.
    async with SessionLocal() as db:
        from models.site_settings import SITE_SETTINGS_ID, SiteSettings

        settings = await db.get(SiteSettings, SITE_SETTINGS_ID)
        assert settings.smtp_password == "super-secret-pw"


async def test_closing_registration_blocks_signup(client):
    admin = await admin_token(client)
    # Open by default: a signup works.
    assert (await _register_resp(client, "early@example.com")).status_code == 201

    await client.put(
        "/api/site-settings/operational",
        json={"registration_open": False},
        headers=_auth(admin),
    )
    # Public read reflects it, and signup is now refused.
    assert (await client.get("/api/site-settings")).json()["registration_open"] is False
    assert (await _register_resp(client, "late@example.com")).status_code == 403

    # Reopening restores it.
    await client.put(
        "/api/site-settings/operational",
        json={"registration_open": True},
        headers=_auth(admin),
    )
    assert (await _register_resp(client, "back@example.com")).status_code == 201


# --- Branding: custom logo + wordmark toggle (Phase 9) ---

# A minimal valid PNG (1x1, transparent) — real magic bytes so any downstream
# sniffing is happy; the endpoint gates on the content-type header regardless.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d4944415478da6360000002000154a24f8f0000000049454e44ae426082"
)


async def test_logo_upload_serve_and_clear(client):
    admin = await admin_token(client)

    # No logo initially → public shape says so, and the stream 404s.
    assert (await client.get("/api/site-settings")).json()["logo_url"] is None
    assert (await client.get("/api/site-settings/logo")).status_code == 404

    resp = await client.post(
        "/api/site-settings/logo",
        files={"file": ("mark.png", _PNG, "image/png")},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["logo_url"] is not None

    # Public read now advertises the logo (unauthenticated).
    logo_url = (await client.get("/api/site-settings")).json()["logo_url"]
    assert logo_url and logo_url.startswith("/api/site-settings/logo?v=")

    # The bytes stream back with the stored content-type + hardening headers.
    served = await client.get("/api/site-settings/logo")
    assert served.status_code == 200
    assert served.content == _PNG
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in served.headers["content-security-policy"]

    # Clearing reverts to the built-in mark.
    cleared = await client.delete("/api/site-settings/logo", headers=_auth(admin))
    assert cleared.status_code == 200
    assert cleared.json()["logo_url"] is None
    assert (await client.get("/api/site-settings/logo")).status_code == 404


async def test_logo_upload_requires_manage_site_settings(client):
    token = await _register(client, "nobody@example.com")
    resp = await client.post(
        "/api/site-settings/logo",
        files={"file": ("mark.png", _PNG, "image/png")},
        headers=_auth(token),
    )
    assert resp.status_code == 403


async def test_logo_upload_rejects_non_image(client):
    admin = await admin_token(client)
    resp = await client.post(
        "/api/site-settings/logo",
        files={"file": ("payload.txt", b"not an image", "text/plain")},
        headers=_auth(admin),
    )
    assert resp.status_code == 415


# --- Email-domain allowlist for public registration (#56) ---


async def test_allowlist_disabled_by_default_email_stays_optional(client):
    # Allowlist off: registration behaves exactly as before — email optional,
    # any domain accepted.
    assert (
        await client.get("/api/site-settings")
    ).json()["email_required"] is False
    resp = await client.post(
        "/api/auth/register",
        json={"display_name": "NoAllowlist", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text


async def test_enabling_allowlist_requires_email_and_makes_it_public(client):
    admin = await admin_token(client)
    resp = await client.put(
        "/api/site-settings/operational",
        json={
            "registration_open": True,
            "email_domain_allowlist_enabled": True,
            "allowed_email_domains": ["Example.COM"],
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email_domain_allowlist_enabled"] is True
    # Normalized: lowercased.
    assert body["allowed_email_domains"] == ["example.com"]

    public = await client.get("/api/site-settings")
    assert public.json()["email_required"] is True
    # The domain list itself never appears on the public shape.
    assert "allowed_email_domains" not in public.json()

    # Missing email while enabled → rejected, generic message.
    missing = await client.post(
        "/api/auth/register",
        json={"display_name": "NoEmailAtAll", "password": "password123"},
    )
    assert missing.status_code == 403
    assert "not permitted" in missing.json()["detail"].lower()

    # Non-matching domain → rejected with the *same* generic message (never
    # discloses the allowlist).
    mismatch = await client.post(
        "/api/auth/register",
        json={
            "display_name": "WrongDomain",
            "password": "password123",
            "email": "person@other.com",
        },
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["detail"] == missing.json()["detail"]

    # Exact domain match → allowed.
    exact = await client.post(
        "/api/auth/register",
        json={
            "display_name": "ExactMatch",
            "password": "password123",
            "email": "person@example.com",
        },
    )
    assert exact.status_code == 201, exact.text

    # Subdomain match → allowed too.
    sub = await client.post(
        "/api/auth/register",
        json={
            "display_name": "SubMatch",
            "password": "password123",
            "email": "person@mail.example.com",
        },
    )
    assert sub.status_code == 201, sub.text


async def test_allowlist_rejects_malformed_domains_on_save(client):
    admin = await admin_token(client)
    for bad_domain in ("@example.com", "http://example.com", "*.example.com", "no-dot"):
        resp = await client.put(
            "/api/site-settings/operational",
            json={
                "registration_open": True,
                "email_domain_allowlist_enabled": True,
                "allowed_email_domains": [bad_domain],
            },
            headers=_auth(admin),
        )
        assert resp.status_code == 422, (bad_domain, resp.text)


async def test_allowlist_caps_domain_count(client):
    admin = await admin_token(client)
    resp = await client.put(
        "/api/site-settings/operational",
        json={
            "registration_open": True,
            "email_domain_allowlist_enabled": True,
            "allowed_email_domains": [f"d{i}.com" for i in range(51)],
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 422


async def test_allowlist_dedupes_domains(client):
    admin = await admin_token(client)
    resp = await client.put(
        "/api/site-settings/operational",
        json={
            "registration_open": True,
            "email_domain_allowlist_enabled": True,
            "allowed_email_domains": ["example.com", "EXAMPLE.com", "example.com"],
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["allowed_email_domains"] == ["example.com"]


async def test_allowlist_does_not_affect_admin_created_accounts(client):
    """The allowlist is public-registration-only — admin-minted accounts
    (Admin → Users) are exempt regardless of the setting."""
    admin = await admin_token(client)
    await client.put(
        "/api/site-settings/operational",
        json={
            "registration_open": True,
            "email_domain_allowlist_enabled": True,
            "allowed_email_domains": ["example.com"],
        },
        headers=_auth(admin),
    )
    resp = await client.post(
        "/api/users",
        json={
            "display_name": "AdminMinted",
            "password": "password123",
            "email": "person@not-allowed.com",
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 201, resp.text


async def test_show_wordmark_round_trips(client):
    admin = await admin_token(client)
    resp = await client.put(
        "/api/site-settings",
        json={
            "platform_name": "ACME",
            "default_palette": "harbor",
            "accent": "signal",
            "show_wordmark": False,
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["show_wordmark"] is False
    assert (await client.get("/api/site-settings")).json()["show_wordmark"] is False
