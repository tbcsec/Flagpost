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
        "active_theme": None,
        "background_style": "none",
        "login_notice": None,
        "registration_open": True,
        "logo_url": None,
        "show_wordmark": True,
        "demo_mode": False,
        "demo_stock_credentials": False,
        "archive_auto_delete": True,
        "archive_retention_days": 30,
        "email_required": False,
        "email_verification_enabled": False,
        "username_changes_enabled": True,
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
        "active_theme": None,
        "background_style": "none",
        "login_notice": None,
        "registration_open": True,
        "logo_url": None,
        "show_wordmark": True,
        "demo_mode": False,
        "demo_stock_credentials": False,
        "archive_auto_delete": True,
        "archive_retention_days": 30,
        "email_required": False,
        "email_verification_enabled": False,
        "username_changes_enabled": True,
    }


async def test_background_style_round_trips_and_is_public(client):
    admin = await admin_token(client)
    resp = await client.put(
        "/api/site-settings",
        json={
            "platform_name": "ACME",
            "default_palette": "harbor",
            "accent": "signal",
            "background_style": "aurora",
        },
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["background_style"] == "aurora"
    # Public read carries it (front-door pages render it pre-auth).
    public = (await client.get("/api/site-settings")).json()
    assert public["background_style"] == "aurora"


async def test_background_style_omitted_leaves_it_unchanged(client):
    # Omit = leave unchanged (the update_checks_enabled precedent): a scripted
    # client changing the platform name must not silently clear a configured
    # background. Resetting requires an explicit "none".
    admin = await admin_token(client)
    await client.put(
        "/api/site-settings",
        json={"platform_name": "A", "default_palette": "harbor", "accent": "signal", "background_style": "aurora"},
        headers=_auth(admin),
    )
    await client.put(
        "/api/site-settings",
        json={"platform_name": "B", "default_palette": "harbor", "accent": "signal"},
        headers=_auth(admin),
    )
    assert (await client.get("/api/site-settings")).json()["background_style"] == "aurora"

    await client.put(
        "/api/site-settings",
        json={"platform_name": "B", "default_palette": "harbor", "accent": "signal", "background_style": "none"},
        headers=_auth(admin),
    )
    assert (await client.get("/api/site-settings")).json()["background_style"] == "none"


async def test_update_rejects_malformed_background_style(client):
    admin = await admin_token(client)
    for bad in ("Aurora", "aurora; }", "url(x)", "a" * 40):
        resp = await client.put(
            "/api/site-settings",
            json={"platform_name": "X", "default_palette": "harbor", "accent": "signal", "background_style": bad},
            headers=_auth(admin),
        )
        assert resp.status_code == 422, (bad, resp.text)


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

    # ...and it decrypts transparently when explicitly loaded, so the mailer
    # gets the real password back. The column is deferred, so undefer it the way
    # the mailer does — a bare attribute access would lazy-load and fail.
    from sqlalchemy.orm import undefer

    async with SessionLocal() as db:
        from models.site_settings import SITE_SETTINGS_ID, SiteSettings

        settings = await db.get(
            SiteSettings,
            SITE_SETTINGS_ID,
            options=[undefer(SiteSettings.smtp_password)],
        )
        assert settings.smtp_password == "super-secret-pw"


async def test_lost_key_does_not_break_the_settings_pages(client, monkeypatch):
    """Regression (review of #109): the SMTP password is deferred so an ordinary
    settings load never decrypts it. A lost/rotated key must NOT take down the
    public branding page or the admin settings page — those are exactly what an
    operator needs to re-enter the secret (ADR-0020 recovery)."""
    from cryptography.fernet import Fernet

    import utils.crypto as crypto

    admin = await admin_token(client)
    await client.put(
        "/api/site-settings/operational",
        json={
            "registration_open": True,
            "smtp_host": "smtp.example.com",
            "smtp_from": "ctf@example.com",
            "smtp_password": "will-become-unreadable",
        },
        headers=_auth(admin),
    )

    # Simulate key loss: swap in a fresh key the stored ciphertext can't decrypt.
    monkeypatch.setenv("SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    crypto._fernet.cache_clear()
    try:
        # Public branding page still loads (never touches the secret).
        assert (await client.get("/api/site-settings")).status_code == 200
        # Admin settings page still loads, and reports the secret as present
        # without decrypting it — so the operator can clear and re-enter it.
        op = await client.get("/api/site-settings/operational", headers=_auth(admin))
        assert op.status_code == 200
        assert op.json()["smtp_password_set"] is True
    finally:
        crypto._fernet.cache_clear()


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

# A minimal valid PNG (1x1, transparent) — real magic bytes, so it passes the
# magic-byte sniff the endpoint gates on (#114).
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d4944415478da6360000002000154a24f8f0000000049454e44ae426082"
)
_GIF = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
_SVG = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'


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


async def test_logo_upload_gates_on_magic_bytes_not_content_type(client):
    """#114: a renamed non-image with a spoofed image/* header must be rejected,
    and the stored type must be derived from the bytes, not the client claim."""
    admin = await admin_token(client)

    # Non-image bytes claiming to be a PNG — the old content-type gate passed
    # this; the magic-byte sniff must not.
    spoofed = await client.post(
        "/api/site-settings/logo",
        files={"file": ("logo.png", b"<html>totally a png</html>", "image/png")},
        headers=_auth(admin),
    )
    assert spoofed.status_code == 415, spoofed.text

    # A real PNG mislabelled as something else is accepted, and the *derived*
    # type wins over the (wrong) client header.
    ok = await client.post(
        "/api/site-settings/logo",
        files={"file": ("logo.bin", _PNG, "application/octet-stream")},
        headers=_auth(admin),
    )
    assert ok.status_code == 200, ok.text
    assert (await client.get("/api/site-settings/logo")).headers[
        "content-type"
    ] == "image/png"


async def test_logo_upload_accepts_gif_and_svg(client):
    admin = await admin_token(client)

    gif = await client.post(
        "/api/site-settings/logo",
        files={"file": ("mark.gif", _GIF, "image/gif")},
        headers=_auth(admin),
    )
    assert gif.status_code == 200, gif.text
    assert (await client.get("/api/site-settings/logo")).headers[
        "content-type"
    ] == "image/gif"

    svg = await client.post(
        "/api/site-settings/logo",
        files={"file": ("mark.svg", _SVG, "image/svg+xml")},
        headers=_auth(admin),
    )
    assert svg.status_code == 200, svg.text
    assert (await client.get("/api/site-settings/logo")).headers[
        "content-type"
    ] == "image/svg+xml"


async def test_logo_upload_rejects_fake_svg(client):
    """A script/text file labelled image/svg+xml but without an <svg> root."""
    admin = await admin_token(client)
    resp = await client.post(
        "/api/site-settings/logo",
        files={"file": ("x.svg", b"<script>alert(1)</script>", "image/svg+xml")},
        headers=_auth(admin),
    )
    assert resp.status_code == 415, resp.text


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


# --- custom sign-in notice (#197) ------------------------------------------

# A minimal ProseMirror doc, the shape the TipTap editor emits.
NOTICE_DOC = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "attrs": {"textAlign": "center"},
            "content": [{"type": "text", "text": "Use your university account."}],
        }
    ],
}

_BASE_PUT = {"platform_name": "A", "default_palette": "harbor", "accent": "signal"}


async def test_login_notice_defaults_to_null_and_is_public(client):
    body = (await client.get("/api/site-settings")).json()
    assert body["login_notice"] is None


async def test_login_notice_round_trips_and_clears_explicitly(client):
    admin = await admin_token(client)
    resp = await client.put(
        "/api/site-settings",
        json={**_BASE_PUT, "login_notice": NOTICE_DOC},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    # Public — the login page is the audience, and it renders pre-auth.
    assert (await client.get("/api/site-settings")).json()["login_notice"] == NOTICE_DOC

    # Omitted = leave unchanged (a scripted PUT that only renames the platform
    # must not silently clear the notice).
    await client.put("/api/site-settings", json=_BASE_PUT, headers=_auth(admin))
    assert (await client.get("/api/site-settings")).json()["login_notice"] == NOTICE_DOC

    # Explicit null = clear (null is the notice's meaningful empty state).
    await client.put(
        "/api/site-settings",
        json={**_BASE_PUT, "login_notice": None},
        headers=_auth(admin),
    )
    assert (await client.get("/api/site-settings")).json()["login_notice"] is None


async def test_login_notice_rejects_a_shapeless_payload(client):
    """The login page feeds this straight to the renderer, so a scripted
    client must not be able to store something that isn't a ProseMirror doc."""
    admin = await admin_token(client)
    for bad in ({}, {"foo": 1}, {"type": "paragraph"}, {"type": "doc"}):
        resp = await client.put(
            "/api/site-settings",
            json={**_BASE_PUT, "login_notice": bad},
            headers=_auth(admin),
        )
        assert resp.status_code == 422, (bad, resp.text)


async def test_login_notice_empty_doc_normalizes_to_null(client):
    """'Empty = no notice' must hold for every client, not just the admin form
    (which normalizes client-side): a doc with no visible text stores as null."""
    admin = await admin_token(client)
    empty = {"type": "doc", "content": [{"type": "paragraph"}]}
    resp = await client.put(
        "/api/site-settings",
        json={**_BASE_PUT, "login_notice": empty},
        headers=_auth(admin),
    )
    assert resp.status_code == 200, resp.text
    assert (await client.get("/api/site-settings")).json()["login_notice"] is None


async def test_login_notice_rejects_an_oversized_doc(client):
    admin = await admin_token(client)
    huge = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "x" * 25_000}],
            }
        ],
    }
    resp = await client.put(
        "/api/site-settings",
        json={**_BASE_PUT, "login_notice": huge},
        headers=_auth(admin),
    )
    assert resp.status_code == 422
    assert "too large" in resp.text
