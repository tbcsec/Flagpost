"""Plain-OAuth2 login endpoints (ADR-0033, issue #193).

The browser-facing half of the ``oauth2`` provider kind — GitHub, Discord, and
any other OAuth 2.0 server described by a preset or by hand. Structurally this
is the OIDC transport with the ID token removed and a userinfo call put in its
place (``utils/oauth2.fetch_identity``); everything either side of that is
deliberately identical, and the shared pieces are imported from
``routers.oidc`` rather than copied:

- ``state`` is minted per login, stored server-side, and consumed exactly once
  at the callback — that single row *is* the CSRF check, since a callback we
  never initiated has nothing to consume;
- the access token never travels in a URL, and neither does ours: the callback
  sets the same httpOnly refresh cookie password login sets, then redirects to a
  frontend page that exchanges it via ``/api/auth/refresh``;
- errors redirect to ``/login?error=<code>`` with a short generic code, because
  a failure here is usually a misconfiguration whose detail (endpoints, client
  ids, internal hostnames) shouldn't be reflected to an unauthenticated browser.

The provider's access token is used for the userinfo call and then dropped —
never stored (ADR-0033): this is authentication, not delegated API access.
"""

from __future__ import annotations

import logging
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
from routers.auth import (
    _issue_session,
    clear_sso_state_cookie,
    set_sso_state_cookie,
    sso_state_cookie_matches,
)
from routers.oidc import _frontend_base, _safe_return_to
from schemas.auth_providers import OAuth2Config, provider_config_or_none
from utils import oauth2 as oauth2_utils
from utils import oidc as oidc_utils
from utils.oauth2 import OAuth2Error

logger = logging.getLogger("oauth2")

router = APIRouter(prefix="/api/auth/oauth2", tags=["oauth2"])

_STATE_TTL = timedelta(minutes=10)


def _fail(reason: str, code: str) -> RedirectResponse:
    """Log the specifics, hand the browser a generic code.

    Deliberately not the OIDC transport's ``_fail`` (whose ``_frontend_base`` and
    ``_safe_return_to`` this module *does* reuse): that one logs "OIDC login
    failed", which would file every OAuth2 failure under the wrong protocol and
    send an operator to the wrong runbook.
    """
    logger.warning("OAuth2 login failed: %s", reason)
    return RedirectResponse(
        f"{_frontend_base()}/login?error={code}", status_code=status.HTTP_302_FOUND
    )


def redirect_uri_for(request: Request, slug: str) -> str:
    """The callback URL, which must match what's registered at the provider.

    Prefers ``PUBLIC_BASE_URL`` for the same reason the OIDC transport does:
    behind a TLS-terminating proxy the backend sees a plain-HTTP hop, so a
    request-derived URI would say ``http://`` and the provider would reject the
    mismatch.
    """
    base = settings.public_base_url.strip().rstrip("/")
    if base:
        return f"{base}/api/auth/oauth2/{slug}/callback"
    return str(request.url_for("oauth2_callback", slug=slug))


async def _enabled_provider(
    db: AsyncSession, slug: str
) -> tuple[IdentityProvider, OAuth2Config] | None:
    """The enabled ``oauth2`` provider behind ``slug`` with its parsed config, or
    ``None``. The re-parse is the ADR-0022 §6 guard: a row whose stored JSON no
    longer validates is a logged skip — indistinguishable from a disabled
    provider — rather than a 500 in a user's face."""
    provider = await db.scalar(
        select(IdentityProvider).where(
            IdentityProvider.slug == slug,
            IdentityProvider.kind == "oauth2",
            IdentityProvider.enabled.is_(True),
        )
    )
    if provider is None:
        return None
    config = provider_config_or_none(provider)
    if not isinstance(config, OAuth2Config):
        logger.warning(
            "provider %s has invalid stored config; treating as unavailable", slug
        )
        return None
    return provider, config


@router.get("/{slug}/login")
async def oauth2_login(
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

    # Validated before the browser is sent anywhere: the authorize URL is the one
    # endpoint the *user agent* visits, so a drifted row pointing somewhere
    # private should fail here rather than become a redirect we handed out.
    try:
        await oauth2_utils.validate_endpoint_url(config.authorize_url)
    except OAuth2Error as exc:
        return _fail(f"authorize URL rejected for {slug}: {exc}", "provider_unavailable")

    state = secrets.token_urlsafe(32)
    verifier, challenge = (
        oidc_utils.generate_pkce() if config.use_pkce else (None, None)
    )

    # Opportunistic sweep so abandoned logins don't accumulate; there's no
    # scheduler hook for this and the table is tiny.
    await db.execute(
        delete(AuthLoginState).where(AuthLoginState.expires_at < utcnow())
    )
    db.add(
        AuthLoginState(
            state=state,
            provider_id=provider.id,
            # Null for a non-PKCE provider — the column is nullable precisely so
            # kinds with different legs can share this table.
            code_verifier=verifier,
            nonce=None,  # no ID token, so nothing to bind a nonce to
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
        "state": state,
    }
    if config.scopes.strip():
        params["scope"] = config.scopes.strip()
    if challenge:
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    # A provider's authorize URL may already carry query parameters (some
    # tenanted servers do), so append rather than assume a bare path.
    separator = "&" if "?" in config.authorize_url else "?"
    redirect = RedirectResponse(
        f"{config.authorize_url}{separator}{urlencode(params)}",
        status_code=status.HTTP_302_FOUND,
    )
    # Bind this login to the initiating browser (F3): the callback must present
    # this cookie matching `state`.
    set_sso_state_cookie(redirect, state, int(_STATE_TTL.total_seconds()))
    return redirect


@router.get("/{slug}/callback", name="oauth2_callback")
async def oauth2_callback(
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

    # Login-CSRF / session-fixation guard (F3): require the state-binding cookie
    # set at /login, proving the same browser started the flow. The single-use
    # state row prevents replay; this prevents a callback URL delivered to a
    # victim from fixating the attacker's session.
    if not sso_state_cookie_matches(request, state):
        return _fail("login state cookie missing or mismatched", "invalid_state")

    # Consume the state row: single-use, so a replayed callback finds nothing.
    login_state = await db.get(AuthLoginState, state)
    if login_state is None:
        return _fail("unknown or already-used state", "invalid_state")
    await db.delete(login_state)
    await db.commit()

    if ensure_aware_utc(login_state.expires_at) < utcnow():
        return _fail("state expired", "expired")

    loaded = await _enabled_provider(db, slug)
    if loaded is None or loaded[0].id != login_state.provider_id:
        return _fail(
            "provider disabled or mismatched between login and callback",
            "provider_unavailable",
        )
    provider, config = loaded

    try:
        access_token = await oauth2_utils.exchange_code(
            token_url=config.token_url,
            code=code,
            redirect_uri=redirect_uri_for(request, slug),
            client_id=config.client_id,
            client_secret=provider.secret,
            code_verifier=login_state.code_verifier,
        )
        # The identity itself. Server-to-server, with a token we obtained
        # ourselves — never one handed to us by the browser (ADR-0033).
        subject, email, email_verified, claims = await oauth2_utils.fetch_identity(
            config, access_token
        )
    except OAuth2Error as exc:
        return _fail(f"oauth2 exchange failed for {slug}: {exc}", "invalid_token")

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

    # Sets the httpOnly refresh cookie on `response`; the access token it returns
    # is intentionally discarded — the frontend fetches its own via
    # /api/auth/refresh so no token is ever put in a URL.
    await _issue_session(db, user, response)
    # The login is done — retire the state-binding cookie.
    clear_sso_state_cookie(response)

    destination = login_state.return_to or "/"
    redirect = RedirectResponse(
        f"{_frontend_base()}/auth/callback?next={destination}",
        status_code=status.HTTP_302_FOUND,
    )
    # RedirectResponse is a different object than the injected `response`, so the
    # cookie _issue_session set has to be carried across explicitly.
    for header_value in response.headers.getlist("set-cookie"):
        redirect.headers.append("set-cookie", header_value)
    logger.info(
        "OAuth2 login via %s: user=%s created=%s", provider.slug, user.id, created
    )
    return redirect
