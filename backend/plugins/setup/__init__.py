"""First-run setup module (ADR-0017, §11.3 required-core).

Mounts the public single-use setup wizard endpoints. Global, not
competition-scoped — hence no competition dependency in the manifest.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.setup import router as setup_router

    app.include_router(setup_router)
