"""Admin CRUD for OIDC providers (ADR-0021, issue #58).

Gated on ``manage_auth_providers`` rather than ``manage_site_settings``: this
surface decides who can log into the platform at all, so it's a materially
higher-stakes grant than the palette and SMTP host that live under site
settings (§7.1).

The ``client_secret`` is **write-only** — every read returns only a
``client_secret_set`` boolean, mirroring how the SMTP password behaves. It's
stored encrypted at rest (ADR-0020, ``utils.crypto.EncryptedString``) because
it must be replayed to the IdP's token endpoint.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.oidc import OidcProvider
from models.user import User
from schemas.oidc import OidcProviderCreate, OidcProviderOut, OidcProviderUpdate
from routers.oidc import redirect_uri_for
from utils import oidc as oidc_utils
from utils.event_bus import event_bus
from utils.oidc import OidcError

router = APIRouter(prefix="/api/admin/oidc-providers", tags=["oidc-admin"])

# Appears in the callback URL registered at the IdP, so keep it boring.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,58}[a-z0-9]$")


def _to_out(provider: OidcProvider, request: Request) -> OidcProviderOut:
    out = OidcProviderOut.model_validate(provider)
    out.client_secret_set = bool(provider.client_secret)
    out.redirect_uri = redirect_uri_for(request, provider.slug)
    return out


async def _provider_or_404(db: AsyncSession, provider_id: str) -> OidcProvider:
    provider = await db.get(OidcProvider, provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found"
        )
    return provider


async def _check_issuer(issuer: str) -> None:
    """Refuse an issuer we can't safely reach. Validated at write time so an
    administrator finds out immediately rather than at someone's first login;
    the same check runs again on every fetch, since DNS can change."""
    # Called through the module (not a direct import) so tests can substitute
    # the network seam — the same convention utils.mailer documents.
    try:
        await oidc_utils.validate_issuer_url(issuer)
    except OidcError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("", response_model=list[OidcProviderOut])
async def list_providers(
    request: Request,
    current_user: User = Depends(require_permission("manage_auth_providers")),
    db: AsyncSession = Depends(get_db),
) -> list[OidcProviderOut]:
    rows = await db.scalars(select(OidcProvider).order_by(OidcProvider.name))
    return [_to_out(p, request) for p in rows]


@router.post("", response_model=OidcProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: OidcProviderCreate,
    request: Request,
    current_user: User = Depends(require_permission("manage_auth_providers")),
    db: AsyncSession = Depends(get_db),
) -> OidcProviderOut:
    slug = body.slug.strip().lower()
    if not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slug must be lowercase letters, numbers and hyphens",
        )
    if await db.scalar(select(OidcProvider.id).where(OidcProvider.slug == slug)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That slug is already in use"
        )
    issuer = body.issuer.strip().rstrip("/")
    await _check_issuer(issuer)

    provider = OidcProvider(
        name=body.name.strip(),
        slug=slug,
        issuer=issuer,
        client_id=body.client_id.strip(),
        client_secret=body.client_secret or None,
        scopes=body.scopes.strip() or "openid email profile",
        enabled=body.enabled,
    )
    db.add(provider)
    await db.commit()
    await event_bus.emit(
        "auth_provider.created",
        {
            "provider_id": provider.id,
            "slug": provider.slug,
            "actor_user_id": current_user.id,
        },
    )
    return _to_out(provider, request)


@router.patch("/{provider_id}", response_model=OidcProviderOut)
async def update_provider(
    provider_id: str,
    body: OidcProviderUpdate,
    request: Request,
    current_user: User = Depends(require_permission("manage_auth_providers")),
    db: AsyncSession = Depends(get_db),
) -> OidcProviderOut:
    provider = await _provider_or_404(db, provider_id)
    changed: list[str] = []

    if body.name is not None:
        provider.name = body.name.strip()
        changed.append("name")
    if body.issuer is not None:
        issuer = body.issuer.strip().rstrip("/")
        await _check_issuer(issuer)
        provider.issuer = issuer
        changed.append("issuer")
    if body.client_id is not None:
        provider.client_id = body.client_id.strip()
        changed.append("client_id")
    if body.scopes is not None:
        provider.scopes = body.scopes.strip() or "openid email profile"
        changed.append("scopes")
    if body.client_secret is not None:
        # "" clears it (a public client relying on PKCE); omitting the field
        # entirely leaves the stored secret untouched, so an edit form doesn't
        # have to round-trip a value it was never shown.
        provider.client_secret = body.client_secret or None
        changed.append("client_secret")
    if body.enabled is not None:
        provider.enabled = body.enabled
        changed.append("enabled")

    await db.commit()
    await event_bus.emit(
        "auth_provider.updated",
        {
            "provider_id": provider.id,
            "slug": provider.slug,
            "changed_fields": changed,
            "actor_user_id": current_user.id,
        },
    )
    return _to_out(provider, request)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: str,
    current_user: User = Depends(require_permission("manage_auth_providers")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a provider. Linked identities cascade, so anyone who signed in
    only through it falls back to local login — which, for a JIT-provisioned
    user, means they have no way in until an administrator sets a password.
    The UI warns about this; disabling is the reversible alternative."""
    provider = await _provider_or_404(db, provider_id)
    slug = provider.slug
    await db.delete(provider)
    await db.commit()
    await event_bus.emit(
        "auth_provider.deleted",
        {"provider_id": provider_id, "slug": slug, "actor_user_id": current_user.id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
