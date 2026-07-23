"""Feedback & Surveys module (ROADMAP #22, §11.3) — the second optional module.

Mounts the survey routes. Per-competition disable is honoured *inside* the
router (every route calls the module-enabled guard), the same pattern the
automations org endpoints use — the loader still mounts an optional module
site-wide; the toggle is runtime state (§11.1 step 3).
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.challenge_ratings import router as ratings_router
    from routers.feedback import router as feedback_router

    app.include_router(feedback_router)
    app.include_router(ratings_router)
