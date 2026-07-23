"""Competitions module — first consumer of the module loader (§11).

The domain implementation (router, schemas, model) stays in the conventional
`routers/`, `schemas/`, `models/` locations per §14; this package is the
module's manifest + `setup` entry point that wires that router into the app.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    # Imported lazily so discovery can read the manifest without importing the
    # whole domain, and to keep module wiring out of import time.
    from routers.awards import router as awards_router
    from routers.brackets import router as brackets_router
    from routers.competitions import router
    from routers.participants import router as participants_router

    app.include_router(router)
    # The individual-mode participant roster (the counterpart to teams); lives
    # with the competitions module since it reads competition membership (§7.5).
    app.include_router(participants_router)
    # Manual judge awards (title/description/points) over the same roster.
    app.include_router(awards_router)
    # Bracket/division self-selection (both modes).
    app.include_router(brackets_router)
