"""First-run setup wizard (ADR-0017): status detection, single-use provisioning,
and the guards it puts around registration until an owner exists.

The `client` fixture seeds an admin *and* stamps `setup_completed_at`, exactly as
a provisioned install has both. Simulating a fresh install therefore means
clearing both — removing only the admin leaves a *configured* install with no
owner, which is a different state entirely and must not reopen the wizard.
"""

from sqlalchemy import select

from auth.deps import user_has_permission
from auth.seed import DEFAULT_ADMIN_EMAIL
from db import SessionLocal
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.user import User


async def _remove_seeded_admin() -> None:
    """Drop the owner but leave the install marked as provisioned."""
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
        if admin is not None:
            await db.delete(admin)  # cascades to the RoleAssignment
            await db.commit()


async def _simulate_fresh_install() -> None:
    """A never-provisioned install: no owner *and* no completion stamp."""
    await _remove_seeded_admin()
    async with SessionLocal() as db:
        settings = await db.get(SiteSettings, SITE_SETTINGS_ID)
        if settings is not None:
            settings.setup_completed_at = None
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


# --- mark_setup_complete: the single writer (#133) ---------------------------


async def test_mark_setup_complete_claims_once_then_no_ops(client):
    """The atomic writer every provisioning path shares: the first call claims
    (True), a second is idempotent (False) — which is exactly how the wizard's
    concurrent loser gets turned away."""
    from auth.setup import mark_setup_complete, setup_is_complete

    await _simulate_fresh_install()

    async with SessionLocal() as db:
        first = await mark_setup_complete(db)
        await db.commit()
    assert first is True

    async with SessionLocal() as db:
        assert await setup_is_complete(db) is True
        second = await mark_setup_complete(db)
        await db.commit()
    assert second is False


async def test_mark_setup_complete_creates_the_singleton_if_absent(client):
    """It ensures the row exists, so no caller has to remember to."""
    from auth.setup import mark_setup_complete

    async with SessionLocal() as db:
        row = await db.get(SiteSettings, SITE_SETTINGS_ID)
        if row is not None:
            await db.delete(row)
            await db.commit()

    async with SessionLocal() as db:
        assert await mark_setup_complete(db) is True
        await db.commit()

    async with SessionLocal() as db:
        row = await db.get(SiteSettings, SITE_SETTINGS_ID)
        assert row is not None and row.setup_completed_at is not None


async def test_status_reflects_provisioning_not_admin_presence(client):
    # Seeded (provisioned) install → configured.
    assert (await client.get("/api/setup/status")).json()["needs_setup"] is False
    # Losing the owner does NOT reopen the wizard — status stays false so the
    # frontend never redirects to a wizard the API will refuse.
    await _remove_seeded_admin()
    assert (await client.get("/api/setup/status")).json()["needs_setup"] is False
    # A genuinely fresh install does need setup.
    await _simulate_fresh_install()
    assert (await client.get("/api/setup/status")).json()["needs_setup"] is True


async def test_configured_install_cannot_be_reclaimed_after_losing_its_admins(client):
    """Regression: the setup wizard must not reopen when admin count hits zero.

    `instance_needs_setup` is "no active global Administrator", which an operator
    can reach through permitted actions — banning one admin, then removing
    another's role assignment past a guard that counted assignment rows rather
    than active users. Gating the wizard on that predicate meant any anonymous
    visitor could then POST /api/setup and be handed a global Administrator
    account on a live install, with its competitions, flags, user records and
    SMTP credentials.
    """
    await _remove_seeded_admin()

    resp = await client.post("/api/setup", json=_setup_body())
    assert resp.status_code == 409, resp.text

    # And no owner was created as a side effect.
    async with SessionLocal() as db:
        assert await db.scalar(select(User).where(User.display_name == "Owner")) is None


async def test_complete_setup_provisions_owner_and_settings(client):
    await _simulate_fresh_install()

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
    await _simulate_fresh_install()
    first = await client.post("/api/setup", json=_setup_body())
    assert first.status_code == 201
    second = await client.post("/api/setup", json=_setup_body(admin={"display_name": "Two", "password": "s3cretpw!"}))
    assert second.status_code == 409


async def test_setup_is_single_use_even_if_the_new_owner_is_removed(client):
    """The completion stamp is one-way — deleting the owner doesn't undo it."""
    await _simulate_fresh_install()
    assert (await client.post("/api/setup", json=_setup_body())).status_code == 201

    async with SessionLocal() as db:
        owner = await db.scalar(select(User).where(User.display_name == "Owner"))
        await db.delete(owner)
        await db.commit()

    retry = await client.post(
        "/api/setup",
        json=_setup_body(admin={"display_name": "Two", "password": "s3cretpw!"}),
    )
    assert retry.status_code == 409


async def test_registration_blocked_before_setup(client):
    await _simulate_fresh_install()
    resp = await client.post(
        "/api/auth/register",
        json={"display_name": "eager", "password": "password123"},
    )
    assert resp.status_code == 403
