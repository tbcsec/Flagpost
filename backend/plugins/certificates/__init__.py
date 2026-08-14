"""Certificates module (ROADMAP #219, ADR-0027) — the fifth optional module.

Mounts the certificate routes: the organiser designer + release + bulk export,
the participant's self-scoped download, the cross-competition "my certificates"
list, and the unauthenticated bundled-asset endpoints (fonts, preset
backgrounds, editor manifest). Per-competition disable is honoured *inside* the
competition-scoped router (every route calls the module-enabled guard), the same
pattern feedback/analytics use — the loader still mounts an optional module
site-wide; the toggle is runtime state (§11.1).

Scheduled release and bulk-export processing run on the kernel scheduler tick
(``utils.automation_scheduler``), not here, so they work in both single-worker
and the multi-worker sidecar (ADR-0025/0026).
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.certificates import assets_router, me_router, router

    app.include_router(router)
    app.include_router(me_router)
    app.include_router(assets_router)
