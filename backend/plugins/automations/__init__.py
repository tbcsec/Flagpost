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


def setup(app, event_bus, db_factory) -> None:
    from routers.automations import router as automations_router
    from utils.automation_engine import handle_event

    app.include_router(automations_router)

    @event_bus.on("*", owner="automations", background=True)
    async def evaluate(event_name: str, payload: dict) -> None:
        await handle_event(db_factory, event_name, payload)
