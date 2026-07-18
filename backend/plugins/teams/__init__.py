"""Teams module (§11) — routes live in routers/teams.py per §14."""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.teams import router

    app.include_router(router)
