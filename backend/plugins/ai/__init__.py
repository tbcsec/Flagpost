"""AI Assistants module (#98, ADR-0023) — Phase 1: provider plumbing.

Mounts the admin provider-config surface (Admin → Site settings → AI). The
module is optional but ships inert — the site master switch defaults off — so
mounting the router is safe: nothing calls the configured endpoint until an
administrator sets one up and enables it. The assistants, their conversation
tables, and the WebSocket streaming flow arrive in later phases.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.ai_admin import router as ai_admin_router

    app.include_router(ai_admin_router)
