"""First-run setup wizard (ADR-0017): status detection, single-use provisioning,
and the guards it puts around registration until an owner exists.

The `client` fixture seeds an admin, so these tests first remove it to simulate a
fresh, unconfigured install.
"""

from sqlalchemy import select

from auth.deps import user_has_permission
from auth.seed import DEFAULT_ADMIN_EMAIL
from db import SessionLocal
from models.user import User


async def _remove_seeded_admin() -> None:
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
        if admin is not None:
            await db.delete(admin)  # cascades to the RoleAssignment
            await db.commit()


def _setup_body(**over):
    body = {
        "admin": {"display_name": "Owner", "password": "s3cretpw!"},
        "platform_name": "ACME CTF",
        "default_palette": "eclipse",
        "accent": "azure",
        "registration_open": False,
    }
    body.update(over)
    return body


async def test_status_reflects_admin_presence(client):
    # Seeded admin present → configured.
    assert (await client.get("/api/setup/status")).json()["needs_setup"] is False
    await _remove_seeded_admin()
    assert (await client.get("/api/setup/status")).json()["needs_setup"] is True


async def test_complete_setup_provisions_owner_and_settings(client):
    await _remove_seeded_admin()

    resp = await client.post("/api/setup", json=_setup_body())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["display_name"] == "Owner"
    admin_id = body["user"]["id"]

    # The new account is a real Administrator and is logged in.
    async with SessionLocal() as db:
        assert await user_has_permission(db, admin_id, "create_competition", None)

    # Setup is now complete, and the branding + policy were applied.
    assert (await client.get("/api/setup/status")).json()["needs_setup"] is False
    public = (await client.get("/api/site-settings")).json()
    assert public["platform_name"] == "ACME CTF"
    assert public["accent"] == "azure"
    assert public["registration_open"] is False

    # The owner can sign in by username.
    login = await client.post(
        "/api/auth/login", json={"identifier": "Owner", "password": "s3cretpw!"}
    )
    assert login.status_code == 200


async def test_setup_rejected_once_configured(client):
    # The seeded admin is still present → the wizard refuses.
    resp = await client.post("/api/setup", json=_setup_body())
    assert resp.status_code == 409


async def test_setup_is_single_use(client):
    await _remove_seeded_admin()
    first = await client.post("/api/setup", json=_setup_body())
    assert first.status_code == 201
    second = await client.post("/api/setup", json=_setup_body(admin={"display_name": "Two", "password": "s3cretpw!"}))
    assert second.status_code == 409


async def test_registration_blocked_before_setup(client):
    await _remove_seeded_admin()
    resp = await client.post(
        "/api/auth/register",
        json={"display_name": "eager", "password": "password123"},
    )
    assert resp.status_code == 403
