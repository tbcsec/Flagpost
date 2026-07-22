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
        json={"email": email, "password": "password123", "display_name": "U"},
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
    }
    # Public shape only — no internal fields leak.
    assert "updated_at" not in body


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
