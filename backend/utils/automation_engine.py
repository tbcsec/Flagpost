"""The automation engine: rule evaluation (ARCHITECTURE.md §5.2).

A pure consumer of the event bus: the automations module subscribes
:func:`handle_event` to ``*`` on the **background lane** (ADR-0012), so
evaluation and action execution never hold up the request that emitted the
event. For each event it loads enabled rules matching ``trigger_type``,
filters by scope (§5.1: competition match, and owner match for personal
rules), AND-evaluates ``conditions`` against the payload, and runs the §5.3
actions of every rule that matches — then bumps the rule's
``trigger_count``/``last_triggered_at`` and emits ``automation.rule_triggered``.

Loop guards (§5.2):

- ``automation.*`` events are never evaluated as triggers — a rule can't
  trigger on the engine's own bookkeeping (utils/event_catalog.py encodes the
  same exclusion for the authoring side).
- A **cascade-depth cap** (``automation_max_depth``): actions emit real §3.2
  events (``score.adjusted``, ``ticket.created``, …) which can legitimately
  trigger further rules; the depth rides a contextvar (inherited by the tasks
  nested emits schedule), and evaluation stops past the cap rather than
  looping. This is the basic runaway guard — the fuller detection/rate scheme
  stays open in §15.

Tenancy (§6.2, §11.3): if the event carries a ``competition_id`` and the
automations module is **disabled for that competition**, nothing fires — not
even global rules; the toggle turns automation off *for that competition's
events*, wholesale.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any

from sqlalchemy import select

from config import settings
from db import utcnow
from models.automation import AutomationRule
from plugins.loader import is_module_enabled
from utils.automation_actions import enrich_payload, execute_action
from utils.event_bus import event_bus

logger = logging.getLogger("automation")

# Cascade depth for the current dispatch chain. Background tasks copy the
# ambient context at creation (asyncio), so an emit from inside an action
# schedules the next evaluation with the incremented depth.
_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "automation_depth", default=0
)

# Comparison operators for conditions (§5.1). Numeric operators coerce both
# sides with float(); a value that won't coerce makes the condition False
# (a misconfigured rule mustn't crash evaluation).
_NUMERIC_OPS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
}

CONDITION_OPERATORS: tuple[str, ...] = (
    "equals",
    "not_equals",
    "contains",
    "gt",
    "gte",
    "lt",
    "lte",
    "exists",
    "not_exists",
)


def _evaluate_condition(condition: dict, payload: dict[str, Any]) -> bool:
    field = condition.get("field", "")
    operator = condition.get("operator", "")
    expected = condition.get("value")
    actual = payload.get(field)

    if operator == "exists":
        return field in payload and actual is not None
    if operator == "not_exists":
        return field not in payload or actual is None
    if operator == "equals":
        return actual == expected or str(actual) == str(expected)
    if operator == "not_equals":
        return not (actual == expected or str(actual) == str(expected))
    if operator == "contains":
        if isinstance(actual, (list, tuple, set)):
            return expected in actual
        return isinstance(actual, str) and str(expected) in actual
    if operator in _NUMERIC_OPS:
        try:
            return _NUMERIC_OPS[operator](float(actual), float(expected))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
    return False


def evaluate_conditions(conditions: list, payload: dict[str, Any]) -> bool:
    """AND-evaluate a rule's conditions; an empty list always matches."""
    return all(_evaluate_condition(c, payload) for c in conditions or [])


def _scope_matches(rule: AutomationRule, payload: dict[str, Any]) -> bool:
    # Competition scope (§5.1): None = global. An event without a
    # competition_id can only match global rules (None != present id).
    if (
        rule.competition_id is not None
        and rule.competition_id != payload.get("competition_id")
    ):
        return False
    # Personal rules fire only on events caused by their owner (§5.1).
    if (
        rule.owner_user_id is not None
        and rule.owner_user_id != payload.get("user_id")
    ):
        return False
    return True


async def handle_event(db_factory, event_name: str, payload: dict[str, Any]) -> None:
    """Evaluate every enabled rule for one emitted event (§5.2)."""
    if event_name.startswith("automation."):
        return
    depth = _depth.get()
    if depth >= settings.automation_max_depth:
        logger.warning(
            "automation cascade depth %s reached on %s; stopping (runaway guard)",
            depth,
            event_name,
        )
        return

    competition_id = payload.get("competition_id")
    async with db_factory() as db:
        # Rules first, module toggle second: this handler runs for *every*
        # emitted event, and the indexed trigger_type lookup is usually empty —
        # so the common no-rules event costs one query, not two.
        rules = (
            (
                await db.execute(
                    select(AutomationRule).where(
                        AutomationRule.trigger_type == event_name,
                        AutomationRule.is_enabled.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        matched = [
            r
            for r in rules
            if _scope_matches(r, payload)
            and evaluate_conditions(r.conditions, payload)
        ]
        if not matched:
            return

        # Per-competition module toggle (§11.3): disabled = no automation for
        # this competition's events, global rules included.
        if competition_id is not None and not await is_module_enabled(
            db, "automations", competition_id
        ):
            return

        token = _depth.set(depth + 1)
        try:
            for rule in matched:
                await run_rule(db, rule, event_name, payload)
        finally:
            _depth.reset(token)


async def run_rule(
    db, rule: AutomationRule, event_name: str, payload: dict[str, Any]
) -> None:
    """Execute a matched rule's actions, update its stats, and announce it.

    Factored out of :func:`handle_event` so the time-based scheduler
    (utils/automation_scheduler.py) fires a rule through the exact same path —
    per-action isolation, ``trigger_count``/``last_triggered_at`` bump, and the
    ``automation.rule_triggered`` event. Condition matching and the cascade
    guard belong to the *caller* (the scheduler computes its own payload)."""
    # Capture identity up front: a failing action rolls the session back, which
    # expires every instance in it — including this rule's own id/name. Reading
    # them afterwards would fire a synchronous lazy-load, illegal in the async
    # session (MissingGreenlet), so keep plain copies for the reload + emit.
    rule_id = rule.id
    rule_name = rule.name
    # Resolve friendly template fields ({user_name}, {challenge_title}, …) once
    # per rule run (#27) — the single choke point both the engine and the
    # time-based scheduler pass through, so every action's render_template sees
    # them. Condition matching (the caller's job) stays on the raw payload.
    try:
        payload = await enrich_payload(db, payload)
    except Exception:  # noqa: BLE001 — enrichment must never block the rule
        logger.exception("payload enrichment failed on rule %s (%s)", rule_id, rule_name)
    needs_reload = False
    for action in rule.actions or []:
        try:
            await execute_action(db, rule, event_name, payload, action)
        except Exception:  # noqa: BLE001 — isolate per action
            logger.exception(
                "action %r failed on rule %s (%s)",
                action.get("type"),
                rule_id,
                rule_name,
            )
            await db.rollback()
            needs_reload = True
    if needs_reload:
        # The rollback expired `rule`; reload it before mutating. A concurrent
        # delete → gone, nothing to bump.
        rule = await db.get(AutomationRule, rule_id)
        if rule is None:
            return
    rule.trigger_count = (rule.trigger_count or 0) + 1
    rule.last_triggered_at = utcnow()
    await db.commit()
    await event_bus.emit(
        "automation.rule_triggered",
        {
            "rule_id": rule_id,
            "rule_name": rule_name,
            "trigger_type": event_name,
            "competition_id": payload.get("competition_id"),
            "triggered_by_user_id": payload.get("user_id"),
        },
    )
