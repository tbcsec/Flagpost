"""External identity module (§7.7.1, §11.3 required-core, ADR-0021).

Mounts the public provider list, the OIDC + SAML login transports, and
the kind-generic admin provider CRUD (ADR-0022). Site-wide rather than competition-scoped, which is why it's required-core with
per-provider `enabled` flags rather than an optional module behind the
`competition_modules` toggle — that mechanism has no site-scoped equivalent.

No event listeners: the §3.2 events this emits (`auth_provider.*`,
`identity.linked`) are consumed by the audit log like any other, and a login
issues its session through the same seam password login uses, so there's
nothing transport-specific to wire up here.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from routers.auth_providers_admin import router as providers_admin_router
    from routers.auth_providers_public import router as providers_public_router
    from routers.oidc import router as oidc_router
    from routers.saml import router as saml_router

    app.include_router(providers_public_router)
    app.include_router(oidc_router)
    app.include_router(saml_router)
    app.include_router(providers_admin_router)
