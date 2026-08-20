"""Custom pages module (#198, ADR-0034, §11.3 required-core).

Mounts the public page reads (sidebar list + one page by slug, both reachable
logged-out) and the `manage_pages` authoring CRUD.

No event listeners: the §3.2 events this emits (`page.created`/`.updated`/
`.deleted`) are consumed by the audit log like any other mutation, so there is
nothing transport-specific to wire up here.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.pages import admin_router, router

    app.include_router(router)
    app.include_router(admin_router)
