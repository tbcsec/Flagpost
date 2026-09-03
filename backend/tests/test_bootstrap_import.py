"""Boot-time baseline import (#357, ADR-0038).

Covers the gate (unconfigured-only, idempotent across restarts), the refuse-to-
start posture on a bad file, the owner-provisioning → setup-complete invariant,
and the public ``demo_stock_credentials`` flag that gates the login credentials
card. The lifespan wiring itself isn't exercised (the test transport runs no
lifespan, per conftest) — ``run_bootstrap_import`` is driven directly.
"""

import json

from sqlalchemy import delete, func, select

from auth.seed import DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD
from auth.setup import instance_needs_setup, setup_is_complete
from config import settings as app_settings
from db import SessionLocal
from models.competition import Competition
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.user import User
from storage.memory import InMemoryStorage
from utils import backup
from utils.bootstrap import BootstrapError, run_bootstrap_import
from utils.event_bus import event_bus

BASELINE_COMP = "Baseline Only Competition"
BASELINE_NAME = "Baseline Corp CTF"


async def _build_baseline(tmp_path) -> str:
    """Seed a distinctive state (branding + a competition), export it to a file,
    then wipe the live DB back to an unconfigured, roles-only state — so a later
    import has to actually repopulate. Returns the file path."""
    async with SessionLocal() as db:
        site = await db.get(SiteSettings, SITE_SETTINGS_ID)
        if site is None:
            site = SiteSettings(id=SITE_SETTINGS_ID)
            db.add(site)
        site.platform_name = BASELINE_NAME
        db.add(
            Competition(
                name=BASELINE_COMP,
                description="d",
                participation_mode="individual",
                visibility="public",
                invite_code="BASE0001",
            )
        )
        await db.commit()

    async with SessionLocal() as db:
        doc = await backup.export_data(db, InMemoryStorage(), list(backup.SECTIONS))
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(doc))

    # Wipe to a genuinely unconfigured state — drop the competition, reset
    # branding, remove the admin (cascades to its role assignment → no active
    # global Administrator) AND clear setup_completed_at. The conftest seed both
    # creates an admin and stamps the flag; clearing only the admin would leave a
    # *configured* install, so the post-import assertions would pass on the stale
    # flag rather than on mark_setup_complete actually running.
    async with SessionLocal() as db:
        await db.execute(delete(Competition).where(Competition.name == BASELINE_COMP))
        site = await db.get(SiteSettings, SITE_SETTINGS_ID)
        site.platform_name = "Flagpost"
        site.setup_completed_at = None
        admin = await db.scalar(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
        if admin is not None:
            await db.delete(admin)
        await db.commit()
    return str(path)


async def test_no_op_when_unset(client, monkeypatch):
    monkeypatch.setattr(app_settings, "bootstrap_backup_file", "")
    async with SessionLocal() as db:
        assert await run_bootstrap_import(db, InMemoryStorage()) is False


async def test_imports_into_unconfigured_instance(client, tmp_path, monkeypatch):
    path = await _build_baseline(tmp_path)
    monkeypatch.setattr(app_settings, "bootstrap_backup_file", path)

    async with SessionLocal() as db:
        assert await instance_needs_setup(db) is True  # precondition: unconfigured
        assert await run_bootstrap_import(db, InMemoryStorage()) is True

    async with SessionLocal() as db:
        # Owner re-provisioned, and setup marked complete despite setup_completed_at
        # being import-immutable (the #133 invariant the bootstrap path upholds).
        assert await instance_needs_setup(db) is False
        assert await setup_is_complete(db) is True
        site = await db.get(SiteSettings, SITE_SETTINGS_ID)
        assert site.platform_name == BASELINE_NAME
        comp = await db.scalar(
            select(Competition).where(Competition.name == BASELINE_COMP)
        )
        assert comp is not None


async def test_reprovisioned_owner_can_log_in(client, tmp_path, monkeypatch):
    path = await _build_baseline(tmp_path)
    monkeypatch.setattr(app_settings, "bootstrap_backup_file", path)
    async with SessionLocal() as db:
        await run_bootstrap_import(db, InMemoryStorage())
    # The baseline carried the admin's password hash, so the imported owner logs
    # in with the original credentials.
    resp = await client.post(
        "/api/auth/login",
        json={"email": DEFAULT_ADMIN_EMAIL, "password": DEFAULT_ADMIN_PASSWORD},
    )
    assert resp.status_code == 200, resp.text


async def test_skips_when_already_configured(client, tmp_path, monkeypatch):
    """An administrator already exists (the seeded one) → the import is a no-op,
    so a restart with the file still mounted never re-imports."""
    path = await _build_baseline(tmp_path)
    # Re-seed an admin so the instance is configured again.
    from auth.seed import seed_admin_user

    async with SessionLocal() as db:
        await seed_admin_user(db)
    monkeypatch.setattr(app_settings, "bootstrap_backup_file", path)

    async with SessionLocal() as db:
        assert await instance_needs_setup(db) is False
        assert await run_bootstrap_import(db, InMemoryStorage()) is False
        # The baseline's competition was NOT imported.
        comp = await db.scalar(
            select(Competition).where(Competition.name == BASELINE_COMP)
        )
        assert comp is None


async def test_missing_file_raises(client, monkeypatch):
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
        await db.delete(admin)
        await db.commit()
    monkeypatch.setattr(app_settings, "bootstrap_backup_file", "/nonexistent/baseline.json")
    async with SessionLocal() as db:
        try:
            await run_bootstrap_import(db, InMemoryStorage())
            assert False, "expected BootstrapError"
        except BootstrapError:
            pass


async def test_invalid_json_raises(client, tmp_path, monkeypatch):
    path = tmp_path / "garbage.json"
    path.write_text("this is not json {{{")
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
        await db.delete(admin)
        await db.commit()
    monkeypatch.setattr(app_settings, "bootstrap_backup_file", str(path))
    async with SessionLocal() as db:
        try:
            await run_bootstrap_import(db, InMemoryStorage())
            assert False, "expected BootstrapError"
        except BootstrapError:
            pass


async def test_wrong_schema_version_raises(client, tmp_path, monkeypatch):
    path = tmp_path / "future.json"
    path.write_text(
        json.dumps({"flagpost_export": True, "schema_version": 999, "data": {}})
    )
    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
        await db.delete(admin)
        await db.commit()
    monkeypatch.setattr(app_settings, "bootstrap_backup_file", str(path))
    async with SessionLocal() as db:
        try:
            await run_bootstrap_import(db, InMemoryStorage())
            assert False, "expected BootstrapError"
        except BootstrapError:
            pass


async def test_emits_platform_imported_event(client, tmp_path, monkeypatch):
    path = await _build_baseline(tmp_path)
    monkeypatch.setattr(app_settings, "bootstrap_backup_file", path)
    seen: list[dict] = []

    async def _capture(_name, payload):
        seen.append(payload)

    event_bus.subscribe("platform.imported", _capture, owner="_test_bootstrap")
    try:
        async with SessionLocal() as db:
            await run_bootstrap_import(db, InMemoryStorage())
    finally:
        event_bus.unsubscribe_owner("_test_bootstrap")

    assert len(seen) == 1
    assert seen[0]["source"] == "bootstrap"
    assert seen[0]["user_id"] is None
    assert seen[0]["created"] > 0


async def test_no_active_owner_baseline_stays_unconfigured_and_quiet(
    client, tmp_path, monkeypatch
):
    """A baseline with no active administrator (here: users/roles stripped) imports
    its content but leaves the instance on the setup wizard, and — once its rows
    already exist — re-runs each boot without re-emitting platform.imported."""
    path = await _build_baseline(tmp_path)
    doc = json.loads((tmp_path / "baseline.json").read_text())
    doc["data"].pop("users", None)
    doc["data"].pop("roles", None)  # drops the admin's role assignment too
    (tmp_path / "baseline.json").write_text(json.dumps(doc))
    monkeypatch.setattr(app_settings, "bootstrap_backup_file", path)

    seen: list[dict] = []

    async def _capture(_name, payload):
        seen.append(payload)

    event_bus.subscribe("platform.imported", _capture, owner="_test_bootstrap_noowner")
    try:
        async with SessionLocal() as db:
            assert await run_bootstrap_import(db, InMemoryStorage()) is True
        # Content imported, but no active owner → still unconfigured.
        async with SessionLocal() as db:
            assert await instance_needs_setup(db) is True
            assert await setup_is_complete(db) is False
            comp = await db.scalar(
                select(Competition).where(Competition.name == BASELINE_COMP)
            )
            assert comp is not None
        # No owner was provisioned, so platform.imported is never emitted (the
        # warning log is the signal instead) — not on the first boot nor on a
        # re-run where the singleton still counts as "created".
        assert seen == []
        async with SessionLocal() as db:
            await run_bootstrap_import(db, InMemoryStorage())
        assert seen == []
    finally:
        event_bus.unsubscribe_owner("_test_bootstrap_noowner")


async def test_public_flag_demo_off(client, monkeypatch):
    monkeypatch.setattr(app_settings, "demo_mode", False)
    monkeypatch.setattr(app_settings, "bootstrap_backup_file", "")
    body = (await client.get("/api/site-settings")).json()
    assert body["demo_mode"] is False
    assert body["demo_stock_credentials"] is False


async def test_public_flag_demo_on_without_baseline(client, monkeypatch):
    monkeypatch.setattr(app_settings, "demo_mode", True)
    monkeypatch.setattr(app_settings, "bootstrap_backup_file", "")
    body = (await client.get("/api/site-settings")).json()
    assert body["demo_mode"] is True
    assert body["demo_stock_credentials"] is True


async def test_public_flag_demo_on_with_baseline_suppresses_card(client, monkeypatch):
    monkeypatch.setattr(app_settings, "demo_mode", True)
    monkeypatch.setattr(app_settings, "bootstrap_backup_file", "/data/baseline.json")
    body = (await client.get("/api/site-settings")).json()
    assert body["demo_mode"] is True
    assert body["demo_stock_credentials"] is False
