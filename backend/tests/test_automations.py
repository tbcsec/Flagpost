"""Automation engine end-to-end (Tier 3 Phase 1, §5): rule CRUD RBAC (org /
global / personal), validation, every §5.3 action executor driven by real
events, scoping, the cascade-depth guard, the per-competition module toggle
gating both the API and the engine, and the §3.2 events.

The engine runs on the background lane (ADR-0012), so tests that trigger it
await ``event_bus.wait_for_background()`` before asserting effects."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from db import SessionLocal
from models.audit_log import AuditLogEntry
from models.automation import Achievement, AutomationRule
from models.challenge import Challenge
from models.competition import Competition
from models.feedback import Survey
from models.hint import Hint, HintReveal
from models.score_adjustment import ScoreAdjustment
from models.ticket import Ticket
from tests.conftest import admin_token
from utils.automation_scheduler import run_time_rules
from utils.event_bus import event_bus

import main  # noqa: E402


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client, email) -> str:
    resp = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "display_name": email.split("@")[0]},
    )
    return resp.json()["access_token"]


async def _competition(client, mode="individual") -> str:
    admin = await admin_token(client)
    return (
        await client.post(
            "/api/competitions",
            json={"name": "CTF", "participation_mode": mode, "visibility": "public"},
            headers=_auth(admin),
        )
    ).json()["id"]


async def _challenge(client, comp, title="Chal", points=100, flag="flag{win}") -> str:
    admin = await admin_token(client)
    chal = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": title, "points": points, "flag": flag},
            headers=_auth(admin),
        )
    ).json()["id"]
    await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/publish", headers=_auth(admin)
    )
    return chal


async def _participant(client, comp, email) -> str:
    """Register + self-serve join (public competition) → Participant role."""
    token = await _register(client, email)
    resp = await client.post(f"/api/competitions/{comp}/join", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return token


async def _judge(client, comp, email) -> str:
    token = await _register(client, email)
    me = (await client.get("/api/auth/me", headers=_auth(token))).json()
    async with SessionLocal() as session:
        from models.role import Role, RoleAssignment

        role = await session.scalar(select(Role).where(Role.name == "Judge"))
        session.add(RoleAssignment(user_id=me["id"], competition_id=comp, role_id=role.id))
        await session.commit()
    return token


async def _solve(client, comp, chal, token, flag="flag{win}") -> None:
    resp = await client.post(
        f"/api/competitions/{comp}/challenges/{chal}/submit",
        json={"flag": flag},
        headers=_auth(token),
    )
    assert resp.json()["correct"] is True, resp.text
    # Engine evaluation is fire-and-forget (ADR-0012) — drain it (and any
    # action-emitted cascade) before asserting effects.
    await event_bus.wait_for_background()


def _notify_rule(trigger="challenge.solved", target="event_user", **overrides) -> dict:
    rule = {
        "name": "Test rule",
        "trigger_type": trigger,
        "conditions": [],
        "actions": [{"type": "notify", "target": target, "title": "Fired: {points}"}],
    }
    rule.update(overrides)
    return rule


async def _create_rule(client, token, comp=None, **overrides) -> dict:
    suffix = f"?competition_id={comp}" if comp else ""
    resp = await client.post(
        f"/api/automations{suffix}", json=_notify_rule(**overrides), headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _notifications(client, token) -> list[dict]:
    return (await client.get("/api/notifications", headers=_auth(token))).json()


# --- RBAC + validation --------------------------------------------------------


async def test_org_rule_crud_requires_automation_permissions(client):
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")
    resp = await client.post(
        f"/api/automations?competition_id={comp}",
        json=_notify_rule(),
        headers=_auth(ada),
    )
    assert resp.status_code == 403
    resp = await client.get(
        f"/api/automations?competition_id={comp}", headers=_auth(ada)
    )
    assert resp.status_code == 403


async def test_judge_manages_competition_rules_but_not_global(client):
    comp = await _competition(client)
    judge = await _judge(client, comp, "judge@example.com")

    rule = await _create_rule(client, judge, comp)
    assert rule["competition_id"] == comp

    # Edit + toggle off.
    body = _notify_rule(is_enabled=False)
    resp = await client.put(
        f"/api/automations/{rule['id']}", json=body, headers=_auth(judge)
    )
    assert resp.status_code == 200 and resp.json()["is_enabled"] is False

    # A per-competition grant doesn't reach global rules (§5.1).
    resp = await client.post(
        "/api/automations", json=_notify_rule(), headers=_auth(judge)
    )
    assert resp.status_code == 403
    resp = await client.get("/api/automations", headers=_auth(judge))
    assert resp.status_code == 403

    resp = await client.delete(f"/api/automations/{rule['id']}", headers=_auth(judge))
    assert resp.status_code == 204


async def test_judge_cannot_edit_another_competitions_rule(client):
    comp_a = await _competition(client)
    comp_b = await _competition(client)
    admin = await admin_token(client)
    judge_a = await _judge(client, comp_a, "judgea@example.com")
    rule_b = await _create_rule(client, admin, comp_b)

    # The permission is checked against the RULE's competition, not the query.
    resp = await client.put(
        f"/api/automations/{rule_b['id']}?competition_id={comp_a}",
        json=_notify_rule(),
        headers=_auth(judge_a),
    )
    assert resp.status_code == 403
    resp = await client.delete(
        f"/api/automations/{rule_b['id']}", headers=_auth(judge_a)
    )
    assert resp.status_code == 403


async def test_admin_creates_global_rule_and_it_lists_with_competition_rules(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    global_rule = await _create_rule(client, admin, name="Global watcher")
    assert global_rule["competition_id"] is None

    comp_rule = await _create_rule(client, admin, comp, name="Comp rule")
    listed = (
        await client.get(
            f"/api/automations?competition_id={comp}", headers=_auth(admin)
        )
    ).json()
    # A competition listing shows its rules plus the globals that fire there.
    assert {r["name"] for r in listed} == {"Global watcher", "Comp rule"}

    global_only = (await client.get("/api/automations", headers=_auth(admin))).json()
    assert [r["name"] for r in global_only] == ["Global watcher"]


async def test_rule_validation_rejects_bad_shapes(client):
    comp = await _competition(client)
    admin = await admin_token(client)

    bad_trigger = _notify_rule(trigger="automation.rule_triggered")
    resp = await client.post(
        f"/api/automations?competition_id={comp}", json=bad_trigger, headers=_auth(admin)
    )
    assert resp.status_code == 422  # automation.* is never triggerable (§5.2)

    bad_operator = _notify_rule(
        conditions=[{"field": "points", "operator": "matches", "value": "x"}]
    )
    resp = await client.post(
        f"/api/automations?competition_id={comp}", json=bad_operator, headers=_auth(admin)
    )
    assert resp.status_code == 422

    bad_action = _notify_rule(actions=[{"type": "launch_missiles"}])
    resp = await client.post(
        f"/api/automations?competition_id={comp}", json=bad_action, headers=_auth(admin)
    )
    assert resp.status_code == 422


async def test_rule_crud_emits_events(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    rule = await _create_rule(client, admin, comp)
    await client.delete(f"/api/automations/{rule['id']}", headers=_auth(admin))

    async with SessionLocal() as session:
        names = (
            await session.scalars(
                select(AuditLogEntry.event_name).where(
                    AuditLogEntry.event_name.like("automation.rule_%")
                )
            )
        ).all()
    assert "automation.rule_created" in names
    assert "automation.rule_deleted" in names


async def test_catalog_generates_the_builder(client):
    token = await admin_token(client)  # an admin sees every trigger
    catalog = (await client.get("/api/automations/catalog", headers=_auth(token))).json()

    triggers = {t["event"] for t in catalog["triggers"]}
    assert "challenge.solved" in triggers
    assert not any(e.startswith("automation.") for e in triggers)
    # Trigger carries its payload fields for condition/placeholder pickers, each
    # with a human label (never the raw key) — "First blood", not is_first_blood.
    solved = next(t for t in catalog["triggers"] if t["event"] == "challenge.solved")
    solved_fields = {f["key"]: f["label"] for f in solved["fields"]}
    assert "is_first_blood" in solved_fields and "points" in solved_fields
    assert solved_fields["is_first_blood"] == "First blood"
    assert solved_fields["challenge_id"] == "Challenge"

    ops = {o["value"]: o for o in catalog["operators"]}
    assert ops["exists"]["unary"] is True
    assert ops["equals"]["unary"] is False

    by_type = {a["type"]: a for a in catalog["actions"]}
    assert set(by_type) == {
        "notify", "send_email", "webhook", "release_hint", "publish_hint",
        "unlock_challenge", "open_survey", "create_ticket", "update_score",
        "create_award", "freeze_scoreboard", "unfreeze_scoreboard",
        "create_announcement",
    }
    assert by_type["notify"]["personal_allowed"] is True
    assert by_type["webhook"]["personal_allowed"] is False
    # Each action ships its config-field descriptors for the generated editor.
    notify_fields = {f["key"]: f for f in by_type["notify"]["fields"]}
    assert notify_fields["target"]["kind"] == "select"
    assert notify_fields["title"]["templateable"] is True

    # Id action params are entity references (name-search dropdowns), not raw id
    # text boxes — and carry which entity they point at (#212, §9 "ids are
    # internal"). The label drops "ID" for the same reason.
    hint_field = by_type["release_hint"]["fields"][0]
    assert hint_field["kind"] == "entity" and hint_field["entity_type"] == "hint"
    assert hint_field["label"] == "Hint"
    chal_field = by_type["unlock_challenge"]["fields"][0]
    assert chal_field["kind"] == "entity" and chal_field["entity_type"] == "challenge"
    survey_field = by_type["open_survey"]["fields"][0]
    assert survey_field["kind"] == "entity" and survey_field["entity_type"] == "survey"

    # A condition value on an id payload field is likewise entity-typed, so the
    # builder can offer a name dropdown for it.
    solved_by_key = {f["key"]: f for f in solved["fields"]}
    assert solved_by_key["challenge_id"]["entity_type"] == "challenge"
    assert solved_by_key["team_id"]["entity_type"] == "team"
    assert solved_by_key["points"]["entity_type"] is None


def test_catalog_covers_every_action_without_drift():
    # The hand-authored field descriptors must stay in lockstep with the
    # executor registry — no action without fields, no fields without an action.
    from utils.automation_actions import ACTIONS
    from utils.automation_catalog import ACTION_FIELDS

    assert set(ACTION_FIELDS) == set(ACTIONS)


def test_every_trigger_has_a_governing_permission():
    from auth.permissions import is_known
    from utils.automation_catalog import TRIGGER_PERMISSIONS
    from utils.event_catalog import TRIGGERABLE_EVENTS

    assert set(TRIGGER_PERMISSIONS) == set(TRIGGERABLE_EVENTS)
    assert all(is_known(p) for p in TRIGGER_PERMISSIONS.values())


# --- trigger authorization (§5.1) --------------------------------------------


async def test_judge_cannot_automate_on_admin_only_events(client):
    comp = await _competition(client)
    judge = await _judge(client, comp, "judge@example.com")

    # A Judge holds no `manage_roles` / `manage_users` / `manage_site_settings`,
    # so an org rule triggering on those events is refused (403) — closing the
    # role.assigned observation leak.
    for trigger in ("role.assigned", "role.created", "user.registered", "site.settings_updated"):
        resp = await client.post(
            f"/api/automations?competition_id={comp}",
            json=_notify_rule(trigger=trigger),
            headers=_auth(judge),
        )
        assert resp.status_code == 403, f"{trigger} should be forbidden for a judge"

    # …but a Judge can automate on events they operate (challenge_view).
    resp = await client.post(
        f"/api/automations?competition_id={comp}",
        json=_notify_rule(trigger="challenge.solved"),
        headers=_auth(judge),
    )
    assert resp.status_code == 201


async def test_admin_can_automate_on_role_events(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    resp = await client.post(
        f"/api/automations?competition_id={comp}",
        json=_notify_rule(trigger="role.assigned"),
        headers=_auth(admin),
    )
    assert resp.status_code == 201


async def test_judge_cannot_switch_a_rule_onto_a_forbidden_trigger(client):
    comp = await _competition(client)
    judge = await _judge(client, comp, "judge@example.com")
    rule = await _create_rule(client, judge, comp)  # challenge.solved — allowed

    resp = await client.put(
        f"/api/automations/{rule['id']}",
        json=_notify_rule(trigger="role.assigned"),
        headers=_auth(judge),
    )
    assert resp.status_code == 403


async def test_catalog_trigger_list_is_permission_scoped(client):
    comp = await _competition(client)
    judge = await _judge(client, comp, "judge@example.com")
    admin = await admin_token(client)

    judge_cat = (
        await client.get(
            f"/api/automations/catalog?competition_id={comp}", headers=_auth(judge)
        )
    ).json()
    judge_triggers = {t["event"] for t in judge_cat["triggers"]}
    # A judge is offered their competition's events, never the admin-only ones.
    assert "challenge.solved" in judge_triggers
    assert "ticket.created" in judge_triggers
    assert "role.assigned" not in judge_triggers
    assert "user.registered" not in judge_triggers
    assert "site.settings_updated" not in judge_triggers

    admin_cat = (
        await client.get(
            f"/api/automations/catalog?competition_id={comp}", headers=_auth(admin)
        )
    ).json()
    assert "role.assigned" in {t["event"] for t in admin_cat["triggers"]}


# --- personal rules (§5.1) ----------------------------------------------------


async def test_personal_rule_crud_needs_no_permission_but_is_notify_self_only(client):
    comp = await _competition(client)
    ada = await _participant(client, comp, "ada@example.com")

    resp = await client.post(
        "/api/automations/personal",
        json=_notify_rule(target="self", competition_id=comp),
        headers=_auth(ada),
    )
    assert resp.status_code == 201, resp.text
    rule = resp.json()
    assert rule["owner_user_id"] is not None

    # Any non-notify-self action is rejected by the schema (§5.1).
    for actions in (
        [{"type": "notify", "target": "event_user", "title": "x"}],
        [{"type": "update_score", "points": 100, "reason": "nope"}],
        [{"type": "webhook", "url": "https://example.com"}],
    ):
        resp = await client.post(
            "/api/automations/personal",
            json=_notify_rule(actions=actions),
            headers=_auth(ada),
        )
        assert resp.status_code == 422, actions

    mine = (await client.get("/api/automations/personal", headers=_auth(ada))).json()
    assert [r["id"] for r in mine] == [rule["id"]]

    # Another user can't see or touch it (404, existence undisclosed).
    bob = await _participant(client, comp, "bob@example.com")
    assert (await client.get("/api/automations/personal", headers=_auth(bob))).json() == []
    resp = await client.delete(
        f"/api/automations/personal/{rule['id']}", headers=_auth(bob)
    )
    assert resp.status_code == 404


async def test_personal_rule_fires_only_for_its_owner(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp)
    ada = await _participant(client, comp, "ada@example.com")
    bob = await _participant(client, comp, "bob@example.com")

    resp = await client.post(
        "/api/automations/personal",
        json=_notify_rule(target="self", competition_id=comp, name="My solves"),
        headers=_auth(ada),
    )
    assert resp.status_code == 201

    await _solve(client, comp, chal, bob)  # someone else's event → silent
    assert await _notifications(client, ada) == []

    chal2 = await _challenge(client, comp, title="Two", flag="flag{two}")
    await _solve(client, comp, chal2, ada, flag="flag{two}")
    notifs = await _notifications(client, ada)
    assert len(notifs) == 1 and notifs[0]["type"] == "challenge.solved"


# --- the engine + executors, driven by real events ---------------------------


async def test_notify_rule_fires_on_solve_with_template_and_stats(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp, points=100)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    rule = await _create_rule(client, admin, comp)
    await _solve(client, comp, chal, ada)

    notifs = await _notifications(client, ada)
    assert len(notifs) == 1
    assert notifs[0]["title"] == "Fired: 100"  # {points} interpolated
    assert notifs[0]["type"] == "challenge.solved"

    fetched = (
        await client.get(f"/api/automations/{rule['id']}", headers=_auth(admin))
    ).json()
    assert fetched["trigger_count"] == 1
    assert fetched["last_triggered_at"] is not None

    async with SessionLocal() as session:
        triggered = (
            await session.scalars(
                select(AuditLogEntry).where(
                    AuditLogEntry.event_name == "automation.rule_triggered"
                )
            )
        ).all()
    assert len(triggered) == 1
    assert triggered[0].payload["rule_id"] == rule["id"]


async def test_conditions_gate_firing(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp, points=100)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    await _create_rule(
        client,
        admin,
        comp,
        conditions=[{"field": "points", "operator": "gt", "value": 500}],
    )
    await _solve(client, comp, chal, ada)
    assert await _notifications(client, ada) == []  # 100 !> 500


async def test_competition_scoping_isolates_rules(client):
    comp_a = await _competition(client)
    comp_b = await _competition(client)
    chal_a = await _challenge(client, comp_a)
    admin = await admin_token(client)
    ada = await _participant(client, comp_a, "ada@example.com")

    await _create_rule(client, admin, comp_b)  # scoped to B
    await _solve(client, comp_a, chal_a, ada)  # event in A
    assert await _notifications(client, ada) == []


async def test_global_rule_fires_in_any_competition(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    await _create_rule(client, admin)  # global
    await _solve(client, comp, chal, ada)
    notifs = await _notifications(client, ada)
    assert len(notifs) == 1


async def test_disabled_rule_does_not_fire(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    await _create_rule(client, admin, comp, is_enabled=False)
    await _solve(client, comp, chal, ada)
    assert await _notifications(client, ada) == []


async def test_update_score_action_moves_the_scoreboard(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp, points=100)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    await _create_rule(
        client,
        admin,
        comp,
        name="First blood bonus",
        conditions=[{"field": "is_first_blood", "operator": "equals", "value": True}],
        actions=[{"type": "update_score", "points": 50, "reason": "First blood on {challenge_id}"}],
    )
    await _solve(client, comp, chal, ada)

    board = (
        await client.get(f"/api/competitions/{comp}/scoreboard", headers=_auth(ada))
    ).json()
    assert board["entries"][0]["points"] == 150  # 100 solve + 50 bonus

    async with SessionLocal() as session:
        adjustment = await session.scalar(select(ScoreAdjustment))
        assert adjustment.points == 50 and adjustment.team_id is None
        assert "First blood on" in adjustment.reason
        names = (
            await session.scalars(select(AuditLogEntry.event_name))
        ).all()
    assert "score.adjusted" in names

    # A second solver isn't first blood → no second adjustment.
    bob = await _participant(client, comp, "bob@example.com")
    await _solve(client, comp, chal, bob)
    async with SessionLocal() as session:
        count = await session.scalar(select(func.count(ScoreAdjustment.id)))
    assert count == 1


async def test_create_award_action_grants_points_and_a_badge(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp, points=100)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    await _create_rule(
        client,
        admin,
        comp,
        actions=[
            {
                "type": "create_award",
                "title": "First Blood",
                "description": "On {challenge_id}",
                "points": 25,
            }
        ],
        conditions=[{"field": "is_first_blood", "operator": "equals", "value": True}],
    )
    await _solve(client, comp, chal, ada)

    async with SessionLocal() as session:
        achievement = await session.scalar(select(Achievement))
        assert achievement is not None
        assert achievement.title == "First Blood"
        assert achievement.points == 25
        assert achievement.competition_id == comp
        names = (await session.scalars(select(AuditLogEntry.event_name))).all()
    assert "achievement.awarded" in names

    # The award's points fold into the scoreboard (100 solve + 25 award).
    board = (
        await client.get(f"/api/competitions/{comp}/scoreboard", headers=_auth(ada))
    ).json()
    assert board["entries"][0]["points"] == 125


async def test_release_hint_action_is_free_and_idempotent(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp)
    chal2 = await _challenge(client, comp, title="Two", flag="flag{two}")
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    hint = (
        await client.post(
            f"/api/competitions/{comp}/challenges/{chal2}/hints",
            json={"body": "look closer", "cost": 40},
            headers=_auth(admin),
        )
    ).json()

    await _create_rule(
        client,
        admin,
        comp,
        actions=[{"type": "release_hint", "hint_id": hint["id"]}],
    )
    await _solve(client, comp, chal, ada)

    async with SessionLocal() as session:
        reveal = await session.scalar(select(HintReveal))
        assert reveal is not None
        assert reveal.cost_charged == 0  # granted, not bought
        assert reveal.hint_id == hint["id"]
        names = (await session.scalars(select(AuditLogEntry.event_name))).all()
    assert "hint.released" in names

    # Solving another challenge doesn't duplicate the reveal (idempotent).
    chal3 = await _challenge(client, comp, title="Three", flag="flag{three}")
    await _solve(client, comp, chal3, ada, flag="flag{three}")
    async with SessionLocal() as session:
        count = await session.scalar(select(func.count(HintReveal.id)))
    assert count == 1


async def test_publish_hint_action_makes_a_hidden_hint_visible(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    # A hidden hint a rule publishes to everyone when the challenge is solved
    # (distinct from release_hint, which grants it to just the solver).
    hint = (
        await client.post(
            f"/api/competitions/{comp}/challenges/{chal}/hints",
            json={"body": "revealed later", "cost": 0, "hidden": True},
            headers=_auth(admin),
        )
    ).json()
    assert hint["hidden"] is True

    await _create_rule(
        client, admin, comp,
        name="Publish hint on solve",
        actions=[{"type": "publish_hint", "hint_id": hint["id"]}],
    )
    await _solve(client, comp, chal, ada)

    # Now visible (staff list shows hidden=false) and hint.published fired.
    staff_list = (
        await client.get(
            f"/api/competitions/{comp}/challenges/{chal}/hints", headers=_auth(admin)
        )
    ).json()
    assert staff_list[0]["hidden"] is False
    async with SessionLocal() as session:
        names = (await session.scalars(select(AuditLogEntry.event_name))).all()
    assert "hint.published" in names


async def test_unlock_challenge_action_respects_tenancy(client):
    comp = await _competition(client)
    comp_other = await _competition(client)
    chal = await _challenge(client, comp)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    # A draft bonus challenge in the same competition, and one in another.
    bonus = (
        await client.post(
            f"/api/competitions/{comp}/challenges",
            json={"title": "Bonus", "points": 500, "flag": "flag{bonus}"},
            headers=_auth(admin),
        )
    ).json()["id"]
    foreign = (
        await client.post(
            f"/api/competitions/{comp_other}/challenges",
            json={"title": "Foreign", "points": 500, "flag": "flag{f}"},
            headers=_auth(admin),
        )
    ).json()["id"]

    await _create_rule(
        client, admin, comp,
        name="Unlock bonus",
        actions=[{"type": "unlock_challenge", "challenge_id": bonus}],
    )
    await _create_rule(
        client, admin, comp,
        name="Cross-tenant attempt",
        actions=[{"type": "unlock_challenge", "challenge_id": foreign}],
    )
    await _solve(client, comp, chal, ada)

    async with SessionLocal() as session:
        assert (await session.get(Challenge, bonus)).state == "published"
        # §6.2: the cross-competition config skipped, challenge untouched.
        assert (await session.get(Challenge, foreign)).state == "draft"
        names = (await session.scalars(select(AuditLogEntry.event_name))).all()
    assert "challenge.published" in names


async def test_create_ticket_action(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    await _create_rule(
        client,
        admin,
        comp,
        actions=[{
            "type": "create_ticket",
            "subject": "Auto: solve review for {challenge_id}",
            "body": "Automatic thread for this solve.",
        }],
    )
    await _solve(client, comp, chal, ada)

    async with SessionLocal() as session:
        ticket = await session.scalar(select(Ticket))
        assert ticket is not None
        assert ticket.subject.startswith("Auto: solve review for ")
        assert ticket.challenge_id == chal
        names = (await session.scalars(select(AuditLogEntry.event_name))).all()
    assert "ticket.created" in names


async def test_send_email_action_interpolates(client, monkeypatch):
    sent: list[dict] = []

    async def fake_send(to, subject, body):
        sent.append({"to": to, "subject": subject, "body": body})
        return True

    from utils import mailer

    monkeypatch.setattr(mailer, "send_email", fake_send)

    comp = await _competition(client)
    chal = await _challenge(client, comp, points=100)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    await _create_rule(
        client,
        admin,
        comp,
        actions=[{
            "type": "send_email",
            "to": ["staff@example.com"],
            "subject": "Solve: {points} points",
            "body": "Challenge {challenge_id} was solved.",
        }],
    )
    await _solve(client, comp, chal, ada)

    assert len(sent) == 1
    assert sent[0]["to"] == ["staff@example.com"]
    assert sent[0]["subject"] == "Solve: 100 points"
    assert chal in sent[0]["body"]


class _FakeResponse:
    status_code = 200


class _FakeHttpxClient:
    """Captures webhook POSTs so tests can assert without a real request.
    Accepts whatever kwargs _execute_webhook passes (follow_redirects, json,
    content, headers)."""

    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        _FakeHttpxClient.calls.append({"url": url, **kwargs})
        return _FakeResponse()


def _fake_webhook(monkeypatch):
    """Fake httpx + skip the SSRF resolver (its own tests cover that), so a
    webhook test is hermetic and about payload/headers, not DNS."""
    import httpx

    from utils import webhook_security

    _FakeHttpxClient.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeHttpxClient)

    async def _ok(url):
        return None

    monkeypatch.setattr(webhook_security, "validate_webhook_url", _ok)
    return _FakeHttpxClient.calls


async def test_webhook_action_posts_structured_event_and_strips_headers(client, monkeypatch):
    calls = _fake_webhook(monkeypatch)
    comp = await _competition(client)
    chal = await _challenge(client, comp)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    await _create_rule(
        client,
        admin,
        comp,
        actions=[{
            "type": "webhook",
            "url": "https://hooks.example.com/x",
            # X-Token is kept; Authorization + X-Forwarded-For are stripped (§5.4).
            "headers": {
                "X-Token": "abc",
                "Authorization": "Bearer secret",
                "X-Forwarded-For": "10.0.0.1",
            },
        }],
    )
    await _solve(client, comp, chal, ada)

    assert len(calls) == 1
    assert calls[0]["url"] == "https://hooks.example.com/x"
    assert calls[0]["json"]["event"] == "challenge.solved"
    assert calls[0]["json"]["payload"]["challenge_id"] == chal
    assert calls[0]["headers"] == {"X-Token": "abc"}


async def test_webhook_template_body_escapes_and_defangs_adversarial_values(client, monkeypatch):
    import json as _json

    calls = _fake_webhook(monkeypatch)
    comp = await _competition(client)
    admin = await admin_token(client)

    # Rule first, then publish the hostile-titled challenge so the rule is live
    # when challenge.published fires (its payload carries `title`).
    await _create_rule(
        client,
        admin,
        comp,
        trigger="challenge.published",
        actions=[{
            "type": "webhook",
            "url": "https://hooks.example.com/slack",
            "content_type": "application/json",
            "body_template": '{"text":"Solved: {title}"}',
        }],
    )
    # A title that is both a JSON-injection and a mass-ping attempt (§5.4).
    hostile = '@everyone","admin":true'
    await _challenge(client, comp, title=hostile, flag="flag{x}")
    await event_bus.wait_for_background()

    assert len(calls) == 1
    body = calls[0]["content"].decode()
    parsed = _json.loads(body)  # still valid JSON — value didn't break out
    # The injected key isn't a real sibling; it survives only as escaped text.
    assert '\\"admin\\":true' in body
    assert parsed.get("admin") is None
    assert "admin" in parsed["text"]
    # @everyone was defanged: the literal token no longer renders as a ping.
    assert "@everyone" not in parsed["text"]
    assert "everyone" in parsed["text"]
    assert calls[0]["headers"]["Content-Type"] == "application/json"


async def test_cascade_depth_guard_stops_rule_loops(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    # A fires on the solve; B fires on A's score.adjusted — and on its own,
    # which without the depth cap would loop forever.
    await _create_rule(
        client, admin, comp,
        name="A",
        actions=[{"type": "update_score", "points": 1, "reason": "a"}],
    )
    await _create_rule(
        client, admin, comp,
        name="B",
        trigger="score.adjusted",
        actions=[{"type": "update_score", "points": 1, "reason": "b"}],
    )
    await _solve(client, comp, chal, ada)  # completes = the loop was stopped

    async with SessionLocal() as session:
        count = await session.scalar(select(func.count(ScoreAdjustment.id)))
    # depth 0: solve → A (adj 1) · depth 1: score.adjusted → B (adj 2) ·
    # depth 2: score.adjusted → B (adj 3) · depth 3: capped.
    assert count == 3


# --- the per-competition module toggle (§11.3) --------------------------------


async def test_module_toggle_rbac_and_invariants(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    listed = (
        await client.get(f"/api/competitions/{comp}/modules", headers=_auth(admin))
    ).json()
    by_id = {m["id"]: m for m in listed}
    assert by_id["automations"] == {
        "id": "automations", "name": "Automations", "version": "1.0.0",
        "enabled": True, "required_core": False,
    }
    # The inventory also lists required-core modules, locked on (§11.3).
    assert by_id["tickets"]["required_core"] is True
    assert by_id["tickets"]["enabled"] is True

    # Participants can't see or flip module state.
    resp = await client.get(f"/api/competitions/{comp}/modules", headers=_auth(ada))
    assert resp.status_code == 403
    resp = await client.put(
        f"/api/competitions/{comp}/modules/automations",
        json={"enabled": False},
        headers=_auth(ada),
    )
    assert resp.status_code == 403

    # Unknown module 404; required-core 409 (§11.3).
    resp = await client.put(
        f"/api/competitions/{comp}/modules/nonsense",
        json={"enabled": False},
        headers=_auth(admin),
    )
    assert resp.status_code == 404
    resp = await client.put(
        f"/api/competitions/{comp}/modules/tickets",
        json={"enabled": False},
        headers=_auth(admin),
    )
    assert resp.status_code == 409

    # A real flip works and emits its §3.2 event.
    resp = await client.put(
        f"/api/competitions/{comp}/modules/automations",
        json={"enabled": False},
        headers=_auth(admin),
    )
    assert resp.status_code == 200 and resp.json()["enabled"] is False
    async with SessionLocal() as session:
        names = (await session.scalars(select(AuditLogEntry.event_name))).all()
    assert "module.disabled" in names


async def test_enabled_modules_endpoint_is_member_readable(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    # A participant (challenge_view, not edit_competition) can read the enabled
    # set — it's what gates their nav. Optional modules only; no required-core.
    enabled = (
        await client.get(
            f"/api/competitions/{comp}/modules/enabled", headers=_auth(ada)
        )
    ).json()
    assert "feedback" in enabled and "automations" in enabled
    assert "tickets" not in enabled  # required-core is never listed here

    # Disabling a module drops it from the member-readable set.
    await client.put(
        f"/api/competitions/{comp}/modules/feedback",
        json={"enabled": False},
        headers=_auth(admin),
    )
    enabled = (
        await client.get(
            f"/api/competitions/{comp}/modules/enabled", headers=_auth(ada)
        )
    ).json()
    assert "feedback" not in enabled and "automations" in enabled


async def test_disabled_module_stops_engine_and_api(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    rule = await _create_rule(client, admin, comp)
    await client.put(
        f"/api/competitions/{comp}/modules/automations",
        json={"enabled": False},
        headers=_auth(admin),
    )

    # Engine: nothing fires for this competition's events — the rule's stats
    # stay untouched and no notification lands.
    await _solve(client, comp, chal, ada)
    assert await _notifications(client, ada) == []
    async with SessionLocal() as session:
        stored = await session.get(AutomationRule, rule["id"])
        assert stored.trigger_count == 0

    # API: the competition's rule surface 404s while disabled (§11.1 step 3).
    resp = await client.get(
        f"/api/automations?competition_id={comp}", headers=_auth(admin)
    )
    assert resp.status_code == 404

    # Re-enable → fires again.
    await client.put(
        f"/api/competitions/{comp}/modules/automations",
        json={"enabled": True},
        headers=_auth(admin),
    )
    chal2 = await _challenge(client, comp, title="Two", flag="flag{two}")
    await _solve(client, comp, chal2, ada, flag="flag{two}")
    assert len(await _notifications(client, ada)) == 1


# --- open_survey action + the time-remaining scheduler (survey/automation glue) ---


async def _create_survey(client, comp, admin, *, title="Feedback") -> str:
    return (
        await client.post(
            f"/api/competitions/{comp}/surveys",
            json={"title": title, "description": None},
            headers=_auth(admin),
        )
    ).json()["id"]


async def _set_end_at(comp: str, when) -> None:
    async with SessionLocal() as session:
        competition = await session.get(Competition, comp)
        competition.end_at = when
        await session.commit()


async def test_open_survey_action_opens_and_emits(client):
    comp = await _competition(client)
    chal = await _challenge(client, comp)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")
    survey = await _create_survey(client, comp, admin)  # closed

    await _create_rule(
        client, admin, comp,
        actions=[{"type": "open_survey", "survey_id": survey}],
    )
    await _solve(client, comp, chal, ada)

    async with SessionLocal() as session:
        assert (await session.get(Survey, survey)).is_open is True
        names = (await session.scalars(select(AuditLogEntry.event_name))).all()
    assert "survey.opened" in names


async def test_open_survey_action_respects_tenancy(client):
    comp = await _competition(client)
    other = await _competition(client)
    chal = await _challenge(client, comp)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")
    foreign = await _create_survey(client, other, admin)  # a survey in another comp

    await _create_rule(
        client, admin, comp,
        actions=[{"type": "open_survey", "survey_id": foreign}],
    )
    await _solve(client, comp, chal, ada)
    # §6.2: the cross-competition survey is untouched.
    async with SessionLocal() as session:
        assert (await session.get(Survey, foreign)).is_open is False


async def test_time_remaining_rule_fires_once_when_threshold_crossed(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    now = datetime.now(timezone.utc)
    await _set_end_at(comp, now + timedelta(minutes=30))  # 30 min left
    survey = await _create_survey(client, comp, admin)

    rule = await _create_rule(
        client, admin, comp,
        trigger="competition.time_remaining",
        conditions=[{"field": "minutes_remaining", "operator": "lte", "value": 60}],
        actions=[{"type": "open_survey", "survey_id": survey}],
    )

    await run_time_rules(SessionLocal, now=now)
    await event_bus.wait_for_background()
    async with SessionLocal() as session:
        assert (await session.get(Survey, survey)).is_open is True
        assert (await session.get(AutomationRule, rule["id"])).trigger_count == 1

    # Dedup: close the survey and tick again — the already-fired rule is skipped.
    async with SessionLocal() as session:
        (await session.get(Survey, survey)).is_open = False
        await session.commit()
    await run_time_rules(SessionLocal, now=now)
    await event_bus.wait_for_background()
    async with SessionLocal() as session:
        assert (await session.get(Survey, survey)).is_open is False


async def test_time_remaining_not_fired_before_threshold(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    now = datetime.now(timezone.utc)
    await _set_end_at(comp, now + timedelta(hours=5))  # 300 min left
    survey = await _create_survey(client, comp, admin)
    await _create_rule(
        client, admin, comp,
        trigger="competition.time_remaining",
        conditions=[{"field": "minutes_remaining", "operator": "lte", "value": 60}],
        actions=[{"type": "open_survey", "survey_id": survey}],
    )
    await run_time_rules(SessionLocal, now=now)
    async with SessionLocal() as session:
        assert (await session.get(Survey, survey)).is_open is False  # 300 !<= 60


async def test_time_remaining_skips_disabled_module(client):
    comp = await _competition(client)
    admin = await admin_token(client)
    now = datetime.now(timezone.utc)
    await _set_end_at(comp, now + timedelta(minutes=30))
    survey = await _create_survey(client, comp, admin)
    await _create_rule(
        client, admin, comp,
        trigger="competition.time_remaining",
        conditions=[{"field": "minutes_remaining", "operator": "lte", "value": 60}],
        actions=[{"type": "open_survey", "survey_id": survey}],
    )
    await client.put(
        f"/api/competitions/{comp}/modules/automations",
        json={"enabled": False}, headers=_auth(admin),
    )
    await run_time_rules(SessionLocal, now=now)
    async with SessionLocal() as session:
        assert (await session.get(Survey, survey)).is_open is False


async def test_time_remaining_to_open_survey_to_notify_participants(client):
    """The headline flow the user asked for: an hour before the competition
    ends, open the post-event survey, which notifies participants."""
    comp = await _competition(client)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")
    now = datetime.now(timezone.utc)
    await _set_end_at(comp, now + timedelta(minutes=45))
    survey = await _create_survey(client, comp, admin, title="Post-event feedback")

    await _create_rule(
        client, admin, comp, name="Open survey near end",
        trigger="competition.time_remaining",
        conditions=[{"field": "minutes_remaining", "operator": "lte", "value": 60}],
        actions=[{"type": "open_survey", "survey_id": survey}],
    )
    await _create_rule(
        client, admin, comp, name="Announce the survey",
        trigger="survey.opened",
        actions=[{
            "type": "notify", "target": "role", "role_name": "Participant",
            "title": "The survey is open: {title}",
        }],
    )

    await run_time_rules(SessionLocal, now=now)
    await event_bus.wait_for_background()

    async with SessionLocal() as session:
        assert (await session.get(Survey, survey)).is_open is True
    notifs = await _notifications(client, ada)
    assert [n["type"] for n in notifs] == ["survey.opened"]
    assert notifs[0]["title"] == "The survey is open: Post-event feedback"


# --- freeze action + lifecycle triggers (Phase 9 adjustments) ----------------


async def test_freeze_scoreboard_action_and_lifecycle_events(client):
    from datetime import timedelta

    from db import SessionLocal, utcnow
    from models.competition import Competition
    from utils.automation_scheduler import emit_lifecycle_events

    comp = await _competition(client)
    admin = await admin_token(client)

    # A rule: when the competition ends, freeze the scoreboard.
    await _create_rule(
        client, admin, comp,
        name="Freeze on end",
        trigger="competition.ended",
        conditions=[],
        actions=[{"type": "freeze_scoreboard"}],
    )

    # Put the competition's end in the past so the lifecycle tick fires ended.
    async with SessionLocal() as s:
        c = await s.get(Competition, comp)
        c.end_at = utcnow() - timedelta(minutes=1)
        c.ended_event_fired = False
        await s.commit()

    await emit_lifecycle_events(SessionLocal)
    await event_bus.wait_for_background()

    # competition.ended fired, and the freeze action ran → board is frozen.
    async with SessionLocal() as s:
        c = await s.get(Competition, comp)
        assert c.ended_event_fired is True
        assert c.scoreboard_frozen_at is not None
        names = (await s.scalars(select(AuditLogEntry.event_name))).all()
    assert "competition.ended" in names
    assert "scoreboard.frozen" in names

    # Idempotent: a second tick doesn't re-fire ended.
    async with SessionLocal() as s:
        before = len([n for n in (await s.scalars(select(AuditLogEntry.event_name))).all() if n == "competition.ended"])
    await emit_lifecycle_events(SessionLocal)
    await event_bus.wait_for_background()
    async with SessionLocal() as s:
        after = len([n for n in (await s.scalars(select(AuditLogEntry.event_name))).all() if n == "competition.ended"])
    assert after == before


async def test_create_announcement_action(client):
    from db import SessionLocal
    from models.announcement import Announcement

    comp = await _competition(client)
    chal = await _challenge(client, comp)
    admin = await admin_token(client)
    ada = await _participant(client, comp, "ada@example.com")

    await _create_rule(
        client, admin, comp,
        name="Announce a solve",
        trigger="challenge.solved",
        conditions=[],
        actions=[{"type": "create_announcement", "title": "Solved!", "body": "Someone solved {challenge_id}"}],
    )
    await _solve(client, comp, chal, ada)

    async with SessionLocal() as s:
        anns = (await s.scalars(select(Announcement).where(Announcement.competition_id == comp))).all()
    assert len(anns) == 1 and anns[0].title == "Solved!"
