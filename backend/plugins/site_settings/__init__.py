"""Site Settings module (§9 site-wide theming, §11.3 required-core).

Mounts the public read / admin-gated update routes for the site-wide theme +
branding singleton. Global, not competition-scoped (ADR-0011) — hence no
competition dependency in the manifest.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.site_settings import router as site_settings_router

    app.include_router(site_settings_router)
