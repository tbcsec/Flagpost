"""Automation engine internals (Tier 3 Phase 1, §5.2): condition evaluation
semantics. Scoping, the depth guard, module gating and the executors are
covered end-to-end in tests/test_automations.py."""

from sqlalchemy import select

import utils.automation_engine as engine
from db import SessionLocal
from models.announcement import Announcement
from models.automation import AutomationRule
from models.challenge import Challenge
from models.competition import Competition, generate_invite_code
from models.user import User
from utils.automation_actions import enrich_payload
from utils.automation_catalog import build_catalog
from utils.automation_engine import evaluate_conditions
from utils.event_bus import event_bus


def _c(field, operator, value=None):
    return {"field": field, "operator": operator, "value": value}


def test_empty_conditions_always_match():
    assert evaluate_conditions([], {"anything": 1}) is True
    assert evaluate_conditions(None, {}) is True


def test_equals_and_not_equals_with_type_coercion():
    payload = {"points": 100, "name": "Ada"}
    assert evaluate_conditions([_c("points", "equals", 100)], payload)
    # String/number coercion: a form-built rule stores "100".
    assert evaluate_conditions([_c("points", "equals", "100")], payload)
    assert evaluate_conditions([_c("name", "equals", "Ada")], payload)
    assert not evaluate_conditions([_c("name", "equals", "Bob")], payload)
    assert evaluate_conditions([_c("name", "not_equals", "Bob")], payload)
    assert not evaluate_conditions([_c("points", "not_equals", "100")], payload)


def test_boolean_payload_fields():
    payload = {"is_first_blood": True}
    assert evaluate_conditions([_c("is_first_blood", "equals", True)], payload)
    assert not evaluate_conditions([_c("is_first_blood", "equals", False)], payload)


def test_numeric_comparisons():
    payload = {"points": 250}
    assert evaluate_conditions([_c("points", "gt", 100)], payload)
    assert evaluate_conditions([_c("points", "gte", 250)], payload)
    assert not evaluate_conditions([_c("points", "lt", 250)], payload)
    assert evaluate_conditions([_c("points", "lte", "250")], payload)
    # Non-numeric operand → False, never a crash (§5.2 defensive evaluation).
    assert not evaluate_conditions([_c("points", "gt", "high")], payload)
    assert not evaluate_conditions(
        [_c("subject", "gt", 10)], {"subject": "not a number"}
    )


def test_contains_on_strings_and_lists():
    assert evaluate_conditions(
        [_c("subject", "contains", "rsa")], {"subject": "baby rsa challenge"}
    )
    assert evaluate_conditions(
        [_c("tags", "contains", "web")], {"tags": ["web", "easy"]}
    )
    assert not evaluate_conditions(
        [_c("tags", "contains", "pwn")], {"tags": ["web"]}
    )
    # contains against a number → False, not a TypeError.
    assert not evaluate_conditions([_c("points", "contains", "1")], {"points": 100})


def test_exists_and_not_exists():
    payload = {"team_id": "t1", "empty": None}
    assert evaluate_conditions([_c("team_id", "exists")], payload)
    assert not evaluate_conditions([_c("empty", "exists")], payload)  # None = absent
    assert evaluate_conditions([_c("missing", "not_exists")], payload)
    assert not evaluate_conditions([_c("team_id", "not_exists")], payload)


def test_conditions_are_anded():
    payload = {"points": 500, "is_first_blood": True}
    both = [_c("points", "gt", 100), _c("is_first_blood", "equals", True)]
    assert evaluate_conditions(both, payload)
    one_fails = [_c("points", "gt", 1000), _c("is_first_blood", "equals", True)]
    assert not evaluate_conditions(one_fails, payload)


def test_unknown_operator_is_false():
    assert not evaluate_conditions([_c("points", "matches", ".*")], {"points": 1})


async def test_run_rule_bumps_stats_even_when_an_action_fails(monkeypatch):
    """Regression: a failing action rolls back the session, which expires every
    instance in it (the rule included). ``run_rule`` must reload the rule before
    bumping its stats rather than trip a synchronous lazy-load in the async
    session (MissingGreenlet). A webhook to an unreachable host hits this path.
    """
    async with SessionLocal() as db:
        rule = AutomationRule(
            name="R",
            trigger_type="challenge.solved",
            conditions=[],
            actions=[{"type": "webhook", "url": "http://example.invalid"}],
            is_enabled=True,
        )
        db.add(rule)
        await db.commit()
        rule_id = rule.id

    async def boom(db, rule, event_name, payload, action):
        raise RuntimeError("action failed")

    monkeypatch.setattr(engine, "execute_action", boom)

    async with SessionLocal() as db:
        rule = await db.get(AutomationRule, rule_id)
        # Must complete without raising despite the rolled-back action.
        await engine.run_rule(db, rule, "challenge.solved", {"foo": "bar"})

    await event_bus.wait_for_background()

    async with SessionLocal() as db:
        reloaded = await db.get(AutomationRule, rule_id)
        assert reloaded.trigger_count == 1
        assert reloaded.last_triggered_at is not None


# --- Friendly template fields (#27) ------------------------------------------


async def test_enrich_payload_resolves_friendly_fields():
    async with SessionLocal() as db:
        comp = Competition(name="Enrich CTF", invite_code=generate_invite_code())
        user = User(display_name="ada", password_hash="x")
        db.add_all([comp, user])
        await db.flush()
        challenge = Challenge(competition_id=comp.id, title="Baby RSA")
        db.add(challenge)
        await db.commit()

        payload = {
            "competition_id": comp.id,
            "user_id": user.id,
            "challenge_id": challenge.id,
            "points": 100,
        }
        enriched = await enrich_payload(db, payload)
        assert enriched["user_name"] == "ada"
        assert enriched["challenge_title"] == "Baby RSA"
        assert enriched["competition_name"] == "Enrich CTF"
        # Ids stay ids — webhooks and conditions need the raw values.
        assert enriched["user_id"] == user.id
        assert enriched["points"] == 100
        # The input payload is never mutated.
        assert "user_name" not in payload

        # An id that no longer resolves falls back to the raw value, so an
        # advertised placeholder never renders as a literal {user_name}.
        broken = await enrich_payload(db, {"user_id": "gone"})
        assert broken["user_name"] == "gone"


async def test_run_rule_renders_friendly_fields_in_templates():
    """End to end through run_rule (#27): a create_announcement body written
    with {user_name}/{challenge_title} renders names, not UUIDs."""
    async with SessionLocal() as db:
        comp = Competition(name="Friendly CTF", invite_code=generate_invite_code())
        user = User(display_name="grace", password_hash="x")
        db.add_all([comp, user])
        await db.flush()
        challenge = Challenge(competition_id=comp.id, title="Warmup")
        rule = AutomationRule(
            name="FB",
            trigger_type="challenge.solved",
            conditions=[],
            actions=[
                {
                    "type": "create_announcement",
                    "title": "First blood!",
                    "body": "{user_name} drew first blood on {challenge_title}.",
                }
            ],
            competition_id=comp.id,
            is_enabled=True,
        )
        db.add_all([challenge, rule])
        await db.commit()

        await engine.run_rule(
            db,
            rule,
            "challenge.solved",
            {
                "competition_id": comp.id,
                "user_id": user.id,
                "challenge_id": challenge.id,
            },
        )

    await event_bus.wait_for_background()

    async with SessionLocal() as db:
        announcement = (await db.scalars(select(Announcement))).first()
        assert announcement is not None
        assert announcement.body == "grace drew first blood on Warmup."


def test_catalog_advertises_friendly_fields():
    triggers = {t["event"]: t["fields"] for t in build_catalog()["triggers"]}
    solved = triggers["challenge.solved"]
    for derived in ("user_name", "team_name", "challenge_title", "competition_name"):
        assert derived in solved
    # The raw ids stay advertised alongside their friendly companions.
    assert "user_id" in solved
    assert "challenge_id" in solved
    # A trigger with a different id vocabulary derives its own names.
    assert "opener_user_name" in triggers["ticket.created"]
    assert "ticket_subject" in triggers["ticket.created"]
