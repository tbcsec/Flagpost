"""Analytics module (ROADMAP #23, §11.3 optional).

Mounts the read-only challenge & team analytics endpoints. No event listeners,
no migration — it aggregates data the required-core modules already record.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.analytics import router as analytics_router

    app.include_router(analytics_router)
