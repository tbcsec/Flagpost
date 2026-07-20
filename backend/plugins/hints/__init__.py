"""Hints module (ROADMAP #15, §11.3 required-core).

Mounts the hint routes (authoring + reveal). The scoring impact of a hint's cost
— subtracted from the revealing subject's scoreboard total, and re-broadcast
live when a hint is revealed — lives in the scoring module, which listens for
``challenge.hint_requested``; this module just owns the resource and its routes.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.hints import router as hints_router

    app.include_router(hints_router)
