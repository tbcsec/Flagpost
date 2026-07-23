"""Dashboard module (ROADMAP #16, §11.3 required-core).

Provides the operational dashboard's read endpoints (stats, recent solves,
challenge health, personal standing). The widget-registration layout that
consumes them lives on the frontend (§10.1); the backend only serves the data
each widget fetches for itself.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.admin_overview import router as admin_overview_router
    from routers.dashboard import router as dashboard_router

    app.include_router(dashboard_router)
    # The site-wide admin overview (cross-competition, §6.3) — a global dashboard
    # alongside the per-competition one.
    app.include_router(admin_overview_router)
