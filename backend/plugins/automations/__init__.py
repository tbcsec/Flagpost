"""Automations module (ARCHITECTURE.md §5, ROADMAP #25) — the first optional
module (§11.3).

Mounts the rules API and subscribes the engine (utils/automation_engine.py) to
the bus as a wildcard consumer on the **background lane** (ADR-0012): rule
evaluation and action execution never hold up the request whose mutation
emitted the event. That lane placement is the whole reason Phase 0's dispatch
split exists — a webhook action may take seconds, and the § 3.1 non-blocking
guarantee has to be real here.

The engine handles its own gating per event (automation.* skip, cascade-depth
cap, and the per-competition module toggle), so this setup stays a thin wire.
"""

from __future__ import annotations

# Ceiling for one event's whole evaluation: every matched rule, and every
# action within each, run sequentially (#455).
#
# A **policy ceiling, not a derivation** — the work is unbounded in principle,
# since an event can match many rules and a rule can carry many actions. What
# bounds it in practice is that each individual action is itself bounded:
# webhook egress at ``automation_actions.WEBHOOK_DEADLINE_S`` overall (ADR-0013)
# and SMTP at ``mailer.SMTP_TIMEOUT_SECONDS``.
# This ceiling then allows a realistic fan of several slow actions instead of
# the bus's 10s default, which a *single* email action could exhaust on its
# own — cancelling the rest of the run, skipping the trigger-count bump and the
# ``automation.rule_triggered`` emit, and leaving a rule that silently
# half-ran.
EVALUATE_HANDLER_TIMEOUT = 120.0


def setup(app, event_bus, db_factory) -> None:
    from routers.automations import router as automations_router
    from utils.automation_engine import handle_event

    app.include_router(automations_router)

    @event_bus.on(
        "*",
        owner="automations",
        background=True,
        timeout=EVALUATE_HANDLER_TIMEOUT,
    )
    async def evaluate(event_name: str, payload: dict) -> None:
        await handle_event(db_factory, event_name, payload)
