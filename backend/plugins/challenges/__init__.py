"""Challenges module (§11) — the feature the module loader was built for.

Provides the challenge and category routers (categories exist to organize
challenges, ROADMAP #9, so they ship in this module rather than their own).
Domain code lives in routers/schemas/models per §14.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.attachments import router as attachments_router
    from routers.categories import router as categories_router
    from routers.challenges import router as challenges_router

    app.include_router(challenges_router)
    app.include_router(categories_router)
    app.include_router(attachments_router)
