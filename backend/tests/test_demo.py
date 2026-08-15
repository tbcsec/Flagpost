"""Demo mode (config.demo_mode): the public flag, the seeded accounts + sample
data, and the disabled outbound automation actions."""

from sqlalchemy import select

from auth.demo import DEMO_COMPETITION_NAME, seed_demo_data
from config import settings
from db import SessionLocal
from models.competition import Competition
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.user import User


async def test_public_settings_reports_demo_mode(client, monkeypatch):
    assert (await client.get("/api/site-settings")).json()["demo_mode"] is False
    monkeypatch.setattr(settings, "demo_mode", True)
    assert (await client.get("/api/site-settings")).json()["demo_mode"] is True


async def test_demo_seed_creates_accounts_and_is_idempotent(client):
    async with SessionLocal() as db:
        await seed_demo_data(db)
        await seed_demo_data(db)  # second run must be a no-op
    async with SessionLocal() as db:
        names = set((await db.scalars(select(User.display_name))).all())
        assert {"admin", "judge", "participant"} <= names
        comps = (
            await db.scalars(
                select(Competition.name).where(Competition.name == DEMO_COMPETITION_NAME)
            )
        ).all()
        assert len(comps) == 1  # not duplicated by the second run
        # The demo competition is live out of the box, so submissions + the
        # activity simulator work despite the #221 not_started default.
        comp = await db.scalar(
            select(Competition).where(Competition.name == DEMO_COMPETITION_NAME)
        )
        assert comp.status == "running"


async def test_demo_seed_marks_the_install_provisioned(client):
    """Regression: a fresh demo booted straight into the setup wizard.

    The wizard gate keys on `setup_completed_at`, not admin presence
    (GHSA-ccm4-9573-9965). The demo path runs `seed_demo_data` only — never
    `seed_admin_user` — and on a fresh volume the backfill migration runs on an
    empty DB, so nothing stamped the flag and `/api/setup/status` reported
    needs_setup. Clear the fixture's stamp to reproduce that state.
    """
    async with SessionLocal() as db:
        settings_row = await db.get(SiteSettings, SITE_SETTINGS_ID)
        if settings_row is not None:
            settings_row.setup_completed_at = None
            await db.commit()

    assert (await client.get("/api/setup/status")).json()["needs_setup"] is True

    async with SessionLocal() as db:
        await seed_demo_data(db)

    # The demo instance must present its login page, not the wizard.
    assert (await client.get("/api/setup/status")).json()["needs_setup"] is False
    async with SessionLocal() as db:
        settings_row = await db.get(SiteSettings, SITE_SETTINGS_ID)
        assert settings_row.setup_completed_at is not None


async def test_demo_seeded_accounts_can_log_in(client):
    async with SessionLocal() as db:
        await seed_demo_data(db)
    for username in ("admin", "judge", "participant"):
        resp = await client.post(
            "/api/auth/login", json={"identifier": username, "password": "password"}
        )
        assert resp.status_code == 200, f"{username}: {resp.text}"


async def test_demo_disables_outbound_automation_actions(monkeypatch):
    from utils import automation_actions as aa

    called: list[str] = []

    async def marker(db, rule, event, payload, cfg):
        called.append(cfg["type"])

    monkeypatch.setitem(aa.ACTIONS, "webhook", aa.ActionSpec(marker))
    rule = type("R", (), {"id": "r1"})()

    monkeypatch.setattr(settings, "demo_mode", True)
    await aa.execute_action(None, rule, "challenge.solved", {}, {"type": "webhook"})
    assert called == []  # skipped in demo mode

    monkeypatch.setattr(settings, "demo_mode", False)
    await aa.execute_action(None, rule, "challenge.solved", {}, {"type": "webhook"})
    assert called == ["webhook"]  # runs when not a demo


async def test_demo_hides_disabled_actions_from_catalog(monkeypatch):
    from utils.automation_catalog import build_catalog

    monkeypatch.setattr(settings, "demo_mode", True)
    demo_types = {a["type"] for a in build_catalog()["actions"]}
    assert "webhook" not in demo_types and "send_email" not in demo_types

    monkeypatch.setattr(settings, "demo_mode", False)
    normal_types = {a["type"] for a in build_catalog()["actions"]}
    assert "webhook" in normal_types and "send_email" in normal_types
