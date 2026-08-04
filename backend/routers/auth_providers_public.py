"""Public identity-provider list for the login page (ADR-0022).

Kind-agnostic: returns every *enabled*, config-valid, **redirect-kind** provider
(OIDC + SAML today) with the ``kind`` the frontend needs to build the right
login URL (``/api/auth/{kind}/{slug}/login``). A non-redirect kind (LDAP, #101)
is filtered out so it never grows a dead "Sign in with…" button. A drifted row
whose config no longer validates is skipped — the same ADR-0022 §6 guard the
transports apply, so a rendered button never lands on a raw error.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models.identity_provider import IdentityProvider
from schemas.auth_providers import (
    REDIRECT_KINDS,
    PublicProviderOut,
    provider_config_or_none,
)

logger = logging.getLogger("auth-providers")

router = APIRouter(prefix="/api/auth", tags=["auth-providers"])


@router.get("/providers", response_model=list[PublicProviderOut])
async def public_providers(
    db: AsyncSession = Depends(get_db),
) -> list[PublicProviderOut]:
    """Enabled redirect providers only. Public — the login page renders before
    there's a session."""
    rows = await db.scalars(
        select(IdentityProvider)
        .where(
            IdentityProvider.kind.in_(tuple(REDIRECT_KINDS)),
            IdentityProvider.enabled.is_(True),
        )
        .order_by(IdentityProvider.name)
    )
    providers: list[PublicProviderOut] = []
    for provider in rows:
        if provider_config_or_none(provider) is None:
            logger.warning(
                "provider %s has invalid stored config; hiding its login button",
                provider.slug,
            )
            continue
        providers.append(
            PublicProviderOut(slug=provider.slug, name=provider.name, kind=provider.kind)
        )
    return providers
