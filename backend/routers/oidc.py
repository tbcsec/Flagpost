"""OIDC login endpoints (ADR-0021, issue #58).

The browser-facing half of SSO. Three routes:

- ``GET /api/auth/oidc/providers`` — public; the login page's button list.
- ``GET /api/auth/oidc/{slug}/login`` — mints PKCE + ``state`` + ``nonce``,
  stores them server-side, redirects to the IdP.
- ``GET /api/auth/oidc/{slug}/callback`` — validates everything, resolves the
  identity (``auth.external_identity``), issues a session, redirects into the app.

**The access token never travels in a URL.** The callback sets the same
httpOnly refresh cookie password login sets, then redirects to a frontend page
that calls the existing ``/api/auth/refresh`` to obtain an access token into
memory. A token in a redirect would land in browser history, the Referer header
and any intermediary's logs — so the flow deliberately ends with the same
handshake password login already uses, entered from a different door.

Errors redirect to the login page with a short generic ``?error=`` code rather
than rendering the provider's message: a failure here is often a
misconfiguration whose detail (endpoint URLs, client ids, internal hostnames)
shouldn't be reflected to an unauthenticated browser. The specifics go to the
server log.
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db import ensure_aware_utc, get_db, utcnow
from models.identity_provider import AuthLoginState, IdentityProvider
from routers.auth import _issue_session
from schemas.auth_providers import OidcConfig, provider_config_or_none
from schemas.oidc import OidcProviderPublic
from utils import oidc as oidc_utils
from utils.oidc import OidcError

logger = logging.getLogger("oidc")

router = APIRouter(prefix="/api/auth/oidc", tags=["oidc"])

_STATE_TTL = timedelta(minutes=10)


def _frontend_base() -> str:
    origins = settings.cors_origin_list
    return origins[0].rstrip("/") if origins else ""


# Deliberately an allowlist, not a blocklist. A "starts with / but not //" check
# looks sufficient and isn't: browsers normalise backslashes to forward slashes
# in the path, so `/\evil.com` becomes `//evil.com` — protocol-relative, and an
# open redirect. Constraining the whole string to RFC 3986 path/query/fragment
# characters excludes backslashes, control characters and whitespace outright.
_SAFE_RETURN_TO = re.compile(r"^/(?!/)[A-Za-z0-9\-._~!$&'()*+,;=:@%/?#\[\]]*$")


def _safe_return_to(raw: str | None) -> str | None:
    """Only accept a site-relative path; anything else is dropped (falling back
    to ``/``) rather than becoming an open redirect."""
    if not raw or len(raw) > 512 or not _SAFE_RETURN_TO.match(raw):
        return None
    return raw


def redirect_uri_for(request: Request, slug: str) -> str:
    """The callback URL, which must match what's registered at the IdP exactly.

    Prefers ``PUBLIC_BASE_URL`` over the request. Behind a TLS-terminating proxy
    (the documented Caddy topology) the backend sees a plain-HTTP hop, so
    ``request.url_for`` would produce ``http://…`` and the provider would reject
    the mismatch — and uvicorn doesn't run with ``--proxy-headers``. Falling back
    to the request keeps a direct HTTP dev run working with no configuration.
    """
    base = settings.public_base_url.strip().rstrip("/")
    if base:
        return f"{base}/api/auth/oidc/{slug}/callback"
    return str(request.url_for("oidc_callback", slug=slug))


def _fail(reason: str, code: str) -> RedirectResponse:
    logger.warning("OIDC login failed: %s", reason)
    return RedirectResponse(
        f"{_frontend_base()}/login?error={code}", status_code=status.HTTP_302_FOUND
    )


def _claim_is_true(value: object) -> bool:
    """Strictly interpret an OIDC boolean claim like ``email_verified``.

    OIDC Core §5.1 permits these claims to arrive as either a JSON boolean or its
    string form, and several providers emit the string. ``bool()`` is the wrong
    tool: ``bool("false")`` is ``True``, so a provider that serialises the claim
    as a string would have every user read as verified — and this signal gates
    both existing-account linking and (issue #118) the email-domain admission
    check, so a false positive is a real bypass. Accept only a real ``True`` or
    the string ``"true"``.
    """
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


async def _enabled_provider(
    db: AsyncSession, slug: str
) -> tuple[IdentityProvider, OidcConfig] | None:
    """The enabled OIDC provider behind ``slug`` with its parsed config, or
    ``None``. The config re-parse is the ADR-0022 §6 guard: a row whose stored
    JSON no longer validates (a drifted migration, a direct DB edit) is a
    logged skip — indistinguishable from a disabled provider — rather than a
    500 in a user's face at login time."""
    provider = await db.scalar(
        select(IdentityProvider).where(
            IdentityProvider.slug == slug,
            IdentityProvider.kind == "oidc",
            IdentityProvider.enabled.is_(True),
        )
    )
    if provider is None:
        return None
    config = provider_config_or_none(provider)
    if not isinstance(config, OidcConfig):
        logger.warning(
            "provider %s has invalid stored config; treating as unavailable", slug
        )
        return None
    return provider, config


@router.get("/providers", response_model=list[OidcProviderPublic])
async def list_providers(db: AsyncSession = Depends(get_db)) -> list[IdentityProvider]:
    """Enabled redirect providers only. Public — the login page renders before
    auth. Filtered by kind so a future non-redirect provider (LDAP, #101) never
    grows a dead "Sign in with…" button (ADR-0022 §7), and by the same config
    re-parse the login route applies — a drifted row must be indistinguishable
    from a disabled provider *here too*, or it keeps a button whose click lands
    on a raw 404 instead of the §6 logged skip."""
    rows = await db.scalars(
        select(IdentityProvider)
        .where(
            IdentityProvider.kind == "oidc",
            IdentityProvider.enabled.is_(True),
        )
        .order_by(IdentityProvider.name)
    )
    providers = []
    for provider in rows:
        if provider_config_or_none(provider) is None:
            logger.warning(
                "provider %s has invalid stored config; hiding its login button",
                provider.slug,
            )
            continue
        providers.append(provider)
    return providers


@router.get("/{slug}/login")
async def oidc_login(
    slug: str,
    request: Request,
    return_to: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    loaded = await _enabled_provider(db, slug)
    if loaded is None:
        # A disabled or unknown provider is indistinguishable — no probing for
        # which providers an install has configured but not turned on.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider"
        )
    provider, config = loaded

    try:
        document = await oidc_utils.discover(config.issuer)
    except OidcError as exc:
        return _fail(f"discovery failed for {slug}: {exc}", "provider_unavailable")

    verifier, challenge = oidc_utils.generate_pkce()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    # Opportunistic sweep so abandoned logins don't accumulate; there's no
    # scheduler hook for this and the table is tiny.
    await db.execute(
        delete(AuthLoginState).where(AuthLoginState.expires_at < utcnow())
    )
    db.add(
        AuthLoginState(
            state=state,
            provider_id=provider.id,
            code_verifier=verifier,
            nonce=nonce,
            return_to=_safe_return_to(return_to),
            created_at=utcnow(),
            expires_at=utcnow() + _STATE_TTL,
        )
    )
    await db.commit()

    params = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": redirect_uri_for(request, slug),
        "scope": config.scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return RedirectResponse(
        f"{document['authorization_endpoint']}?{urlencode(params)}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/{slug}/callback", name="oidc_callback")
async def oidc_callback(
    slug: str,
    request: Request,
    response: Response,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if error:
        return _fail(f"provider returned error={error}", "provider_denied")
    if not code or not state:
        return _fail("callback missing code or state", "invalid_response")

    # Consume the state row first: single-use, so a replayed callback finds
    # nothing. This is also the CSRF check — a callback we didn't initiate has
    # no matching row.
    login_state = await db.get(AuthLoginState, state)
    if login_state is None:
        return _fail("unknown or already-used state", "invalid_state")
    await db.delete(login_state)
    await db.commit()

    if ensure_aware_utc(login_state.expires_at) < utcnow():
        return _fail("state expired", "expired")

    loaded = await _enabled_provider(db, slug)
    if loaded is None or loaded[0].id != login_state.provider_id:
        return _fail("provider disabled or mismatched between login and callback",
                     "provider_unavailable")
    provider, config = loaded

    try:
        document = await oidc_utils.discover(config.issuer)
        tokens = await oidc_utils.exchange_code(
            document=document,
            code=code,
            redirect_uri=redirect_uri_for(request, slug),
            client_id=config.client_id,
            client_secret=provider.secret,
            code_verifier=login_state.code_verifier,
        )
        claims = await oidc_utils.validate_id_token(
            id_token=tokens["id_token"],
            document=document,
            issuer=config.issuer,
            client_id=config.client_id,
            nonce=login_state.nonce,
        )
    except OidcError as exc:
        return _fail(f"token/id_token validation failed for {slug}: {exc}", "invalid_token")

    subject = claims.get("sub")
    if not subject:
        return _fail("id_token had no sub", "invalid_token")

    email = claims.get("email")
    email_verified = _claim_is_true(claims.get("email_verified"))
    if not email:
        # Some providers only expose the address at the userinfo endpoint.
        info = await oidc_utils.fetch_userinfo(document, tokens.get("access_token", ""))
        email = info.get("email")
        email_verified = _claim_is_true(info.get("email_verified"))
        claims = {**info, **claims}

    # Imported here rather than at module scope to keep the import graph acyclic
    # (auth.external_identity pulls in the event bus, which imports routers).
    from auth.external_identity import IdentityRejected, resolve_identity

    try:
        user, created = await resolve_identity(
            db,
            provider,
            subject=subject,
            email=email,
            email_verified=email_verified,
            claims=claims,
        )
    except IdentityRejected as exc:
        # Site admission policy refused a new account (#118). The generic
        # ?error= code lands on /login without revealing whether the address has
        # a local account.
        return _fail(
            f"admission policy rejected identity via {provider.slug}: {exc.code}",
            exc.code,
        )
    if not user.is_active:
        return _fail(f"user {user.id} is banned", "account_disabled")

    # Sets the httpOnly refresh cookie on `response`; the access token it
    # returns is intentionally discarded — the frontend fetches its own via
    # /api/auth/refresh so no token is ever put in a URL.
    await _issue_session(db, user, response)

    destination = login_state.return_to or "/"
    redirect = RedirectResponse(
        f"{_frontend_base()}/auth/callback?next={destination}",
        status_code=status.HTTP_302_FOUND,
    )
    # RedirectResponse is a different object than the injected `response`, so
    # the cookie _issue_session set has to be carried across explicitly.
    for header_value in response.headers.getlist("set-cookie"):
        redirect.headers.append("set-cookie", header_value)
    logger.info(
        "OIDC login via %s: user=%s created=%s", provider.slug, user.id, created
    )
    return redirect
