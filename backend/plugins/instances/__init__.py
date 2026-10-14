"""Challenge instancing module (#266, ADR-0036).

The seventh optional module. Ships **inert**: routes mount site-wide but launch
is refused until an operator configures a provisioner and enables it
(``InstanceSettings``), on top of the per-competition module toggle — the AI
module's posture (ADR-0023).

``setup`` wires the two routers (competition-scoped launch/ops + site infra
config) and subscribes the **background provisioner**: the launch route commits
a ``requested`` row and emits ``challenge.instance_requested``; this listener
takes it to ``running``/``failed`` off the request path (ADR-0012, ADR-0036 §2).
The TTL/orphan reaper is periodic work and lives on the shared scheduler
(``utils/automation_scheduler``), not here — no new process (ADR-0036 §2).

The subscription declares its own handler timeout, because provisioning is far
slower than the event bus's default 10s cap and was being cancelled mid-run
(#452) — the ceiling and the reaper threshold it must stay under both live in
``utils.instance_service``/``utils.instance_reaper``, derived from one constant.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.instances import router as instances_router
    from routers.instances_settings import router as settings_router
    from utils.instance_service import PROVISION_HANDLER_TIMEOUT, provision

    # Import for its registration side effect, so the "docker" provisioner kind
    # is in the registry from startup (not only after the first launch).
    import utils.provisioner_docker  # noqa: F401

    app.include_router(instances_router)
    app.include_router(settings_router)

    @event_bus.on(
        "challenge.instance_requested",
        owner="instances",
        background=True,
        timeout=PROVISION_HANDLER_TIMEOUT,
    )
    async def _provision(event_name: str, payload: dict) -> None:
        instance_id = payload.get("instance_id")
        if instance_id:
            await provision(db_factory, instance_id)
