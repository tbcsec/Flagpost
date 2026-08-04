"""Admin CRUD for identity providers, all kinds (ADR-0022, generalizing #58).

Gated on ``manage_auth_providers`` rather than ``manage_site_settings``: this
surface decides who can log into the platform at all, so it's a materially
higher-stakes grant than the palette and SMTP host that live under site
settings (§7.1).

The ``secret`` (OIDC client secret; later a SAML SP key / LDAP bind password)
is **write-only** — every read returns only a ``secret_set`` boolean, mirroring
how the SMTP password behaves. It's stored encrypted at rest (ADR-0020,
``utils.crypto.EncryptedString``) because it must be replayed to the far side.

Kind-specific settings live in the ``config`` JSON, validated against the
per-kind model on every write; ``enabled=True`` is refused unless the resulting
config validates, so "enabled but half-configured" isn't reachable through this
API (ADR-0022 §6).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.identity_provider import IdentityProvider
from models.user import User
from schemas.auth_providers import (
    PROVIDER_CONFIG_MODELS,
    OidcConfig,
    ProviderCreate,
    ProviderOut,
    ProviderUpdate,
    parse_provider_config,
)
from routers.oidc import redirect_uri_for
from utils import oidc as oidc_utils
from utils.event_bus import event_bus
from utils.oidc import OidcError

router = APIRouter(prefix="/api/admin/auth-providers", tags=["auth-providers-admin"])

# Appears in the callback URL registered at the IdP, so keep it boring.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,58}[a-z0-9]$")


def _to_out(provider: IdentityProvider, request: Request) -> ProviderOut:
    out = ProviderOut.model_validate(provider)
    out.secret_set = bool(provider.secret)
    if provider.kind == "oidc":
        out.redirect_uri = redirect_uri_for(request, provider.slug)
    return out


async def _provider_or_404(db: AsyncSession, provider_id: str) -> IdentityProvider:
    provider = await db.get(IdentityProvider, provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found"
        )
    return provider


async def _validated_config(kind: str, config: dict) -> dict:
    """Parse ``config`` against its kind's model and return the normalized dump
    (defaults materialized), running kind-specific write-time checks.

    For OIDC that includes reachability-validating the issuer, so an
    administrator finds out immediately rather than at someone's first login;
    the same check runs again on every fetch, since DNS can change.
    """
    try:
        parsed = parse_provider_config(kind, config)
    except ValidationError as exc:
        # Ordered before ValueError, which it *subclasses* in pydantic v2 — the
        # other way round this branch is dead and the 400 detail becomes the
        # raw multi-line pydantic dump (echoing the submitted input) instead of
        # this one-line message.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {kind} config: {exc.errors()[0]['msg']}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if isinstance(parsed, OidcConfig):
        parsed.issuer = parsed.issuer.strip().rstrip("/")
        parsed.client_id = parsed.client_id.strip()
        parsed.scopes = parsed.scopes.strip() or "openid email profile"
        # Called through the module (not a direct import) so tests can
        # substitute the network seam — the same convention utils.mailer uses.
        try:
            await oidc_utils.validate_issuer_url(parsed.issuer)
        except OidcError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    return parsed.model_dump()


def _check_invariants(provider: IdentityProvider) -> None:
    """Cross-field rules on the resulting row (create and update alike)."""
    if provider.kind != "oidc" and provider.posture != "closed":
        # ADR-0022 §2: closed is "the default and only option for SAML/LDAP" —
        # an admin-configured directory/federation is a trusted, closed
        # provider by construction; an open SAML would apply the public-signup
        # gate to a federated IdP, which is the category error the posture
        # split exists to prevent.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"a {provider.kind} provider must have a closed posture",
        )
    if provider.email_is_authoritative and provider.posture != "closed":
        # For an open provider, email trust comes from the IdP's own
        # email_verified claim; the admin override only means something for a
        # closed directory (ADR-0022 §2).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="email_is_authoritative requires a closed posture",
        )
    if provider.enabled:
        # ADR-0022 §6: "enabled but half-configured" must not be reachable.
        try:
            parse_provider_config(provider.kind, provider.config)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot enable a provider whose config is incomplete",
            ) from exc
    if provider.kind == "ldap" and provider.enabled and not provider.secret:
        # The secret is the service account's bind password, and LDAP has no
        # anonymous-bind fallback (ADR-0022 §5) — unlike OIDC (public client +
        # PKCE) and SAML (unsigned AuthnRequests), where an empty secret is a
        # legitimate configuration.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An LDAP provider needs its bind password before it can be enabled",
        )


@router.get("", response_model=list[ProviderOut])
async def list_providers(
    request: Request,
    current_user: User = Depends(require_permission("manage_auth_providers")),
    db: AsyncSession = Depends(get_db),
) -> list[ProviderOut]:
    rows = await db.scalars(select(IdentityProvider).order_by(IdentityProvider.name))
    return [_to_out(p, request) for p in rows]


@router.post("", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(
    body: ProviderCreate,
    request: Request,
    current_user: User = Depends(require_permission("manage_auth_providers")),
    db: AsyncSession = Depends(get_db),
) -> ProviderOut:
    if body.kind not in PROVIDER_CONFIG_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider kind: {body.kind!r}",
        )
    slug = body.slug.strip().lower()
    if not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slug must be lowercase letters, numbers and hyphens",
        )
    if await db.scalar(
        select(IdentityProvider.id).where(IdentityProvider.slug == slug)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That slug is already in use"
        )

    provider = IdentityProvider(
        kind=body.kind,
        posture=body.posture,
        name=body.name.strip(),
        slug=slug,
        email_is_authoritative=body.email_is_authoritative,
        secret=body.secret or None,
        config=await _validated_config(body.kind, body.config),
        enabled=body.enabled,
    )
    _check_invariants(provider)
    db.add(provider)
    await db.commit()
    await event_bus.emit(
        "auth_provider.created",
        {
            "provider_id": provider.id,
            "slug": provider.slug,
            "kind": provider.kind,
            "actor_user_id": current_user.id,
        },
    )
    return _to_out(provider, request)


@router.patch("/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: str,
    body: ProviderUpdate,
    request: Request,
    current_user: User = Depends(require_permission("manage_auth_providers")),
    db: AsyncSession = Depends(get_db),
) -> ProviderOut:
    provider = await _provider_or_404(db, provider_id)
    changed: list[str] = []

    if body.name is not None:
        provider.name = body.name.strip()
        changed.append("name")
    if body.posture is not None:
        provider.posture = body.posture
        changed.append("posture")
    if body.email_is_authoritative is not None:
        provider.email_is_authoritative = body.email_is_authoritative
        changed.append("email_is_authoritative")
    if body.config is not None:
        # Full replacement (the admin form round-trips the whole object).
        provider.config = await _validated_config(provider.kind, body.config)
        changed.append("config")
    if body.secret is not None:
        # "" clears it (a public client relying on PKCE); omitting the field
        # entirely leaves the stored secret untouched, so an edit form doesn't
        # have to round-trip a value it was never shown.
        provider.secret = body.secret or None
        changed.append("secret")
    if body.enabled is not None:
        provider.enabled = body.enabled
        changed.append("enabled")

    _check_invariants(provider)
    await db.commit()
    await event_bus.emit(
        "auth_provider.updated",
        {
            "provider_id": provider.id,
            "slug": provider.slug,
            "kind": provider.kind,
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
    slug, kind = provider.slug, provider.kind
    await db.delete(provider)
    await db.commit()
    await event_bus.emit(
        "auth_provider.deleted",
        {
            "provider_id": provider_id,
            "slug": slug,
            "kind": kind,
            "actor_user_id": current_user.id,
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
