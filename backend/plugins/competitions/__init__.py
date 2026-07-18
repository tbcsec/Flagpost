"""Competitions module — first consumer of the module loader (§11).

The domain implementation (router, schemas, model) stays in the conventional
`routers/`, `schemas/`, `models/` locations per §14; this package is the
module's manifest + `setup` entry point that wires that router into the app.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    # Imported lazily so discovery can read the manifest without importing the
    # whole domain, and to keep module wiring out of import time.
    from routers.competitions import router

    app.include_router(router)
