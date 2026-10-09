"""Marketplace module — Tier 0 content-pack import (#387, ADR-0040).

v1 mounts only the content-pack install route. The registry client, code-based
import, and settings (#389) mount here too as they land, so the marketplace has
one home rather than a second module later.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.content_packs import router as content_packs_router
    from routers.marketplace import router as marketplace_router

    app.include_router(content_packs_router)
    app.include_router(marketplace_router)
