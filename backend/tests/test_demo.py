"""Demo mode (config.demo_mode): the public flag, the seeded accounts + sample
data, and the disabled outbound automation actions."""

from sqlalchemy import select

from auth.demo import DEMO_COMPETITION_NAME, seed_demo_data
from config import settings
from db import SessionLocal
from models.competition import Competition
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
