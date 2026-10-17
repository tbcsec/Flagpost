"""SAML 2.0 login endpoints (#100, ADR-0022 §4).

The browser-facing half of SAML, SP-initiated only. Three routes:

- ``GET  /api/auth/saml/{slug}/login`` — builds an AuthnRequest, stores a
  single-use state row carrying the request id + return path, redirects to the
  IdP (HTTP-Redirect binding).
- ``POST /api/auth/saml/{slug}/acs`` — the Assertion Consumer Service. The IdP
  POSTs a signed assertion here; we verify it (signature-before-trust,
  ``Conditions``, ``InResponseTo``), map the NameID to a subject, resolve the
  identity and issue a session. This is a **cross-site top-level POST**: it
  takes no auth cookie inbound and is not CSRF-protected (there is no session to
  forge yet) — the single-use RelayState + ``InResponseTo`` are the CSRF/replay
  defence, the SAML analogue of the OIDC ``state``, and a state cookie
  (``SameSite=None`` on HTTPS) binds it to the browser that began the login.
- ``GET  /api/auth/saml/{slug}/metadata`` — the SP metadata XML (ACS URL,
  entityId, optional SP cert) for an IdP administrator to consume.

Like OIDC (``routers/oidc``), the flow ends by setting the httpOnly refresh
cookie and 302-ing to a frontend page that calls ``/api/auth/refresh`` — no
access token ever rides a URL. Errors redirect to ``/login?error=`` with a
short generic code; specifics go to the server log.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db import ensure_aware_utc, get_db, utcnow
from models.identity_provider import AuthLoginState, IdentityProvider
from routers.auth import _issue_session, sso_state_cookie_matches
from routers.oidc import _frontend_base, _safe_return_to
from schemas.auth_providers import SamlConfig, provider_config_or_none
from utils import saml as saml_utils

logger = logging.getLogger("saml")

router = APIRouter(prefix="/api/auth/saml", tags=["saml"])

_STATE_TTL = timedelta(minutes=10)

# The SAML login's browser-binding cookie (GHSA-42m4) — deliberately not the
# `sso_login_state` OIDC/OAuth2 share. Their callbacks are top-level GET
# redirects, which carry a SameSite=Lax cookie; the HTTP-POST binding ends in a
# cross-site *POST* from the IdP's page to the ACS, and browsers withhold Lax
# cookies from that — so a Lax binding refused every IdP on another site, i.e.
# every real one, with invalid_state. SameSite=None is what rides that POST, and
# browsers accept None only with Secure, so it needs an https deployment (see
# _state_cookie_policy). Scoped to the SAML routes to keep the cross-site
# exposure narrow; the value is the 256-bit single-use RelayState either way.
SAML_STATE_COOKIE_NAME = "saml_login_state"
SAML_STATE_COOKIE_PATH = "/api/auth/saml"


def _base_url(request: Request) -> str:
    """The externally-visible origin, preferring ``PUBLIC_BASE_URL`` for the
    same reason ``redirect_uri_for`` does (a TLS-terminating proxy makes the
    request look like plain HTTP); falls back to the request for a direct dev
    run. The ACS URL and metadata URLs are built from this and must match what's
    registered at the IdP."""
    base = settings.public_base_url.strip().rstrip("/")
    if base:
        return base
    return f"{request.url.scheme}://{request.url.netloc}"


def _state_cookie_policy(request: Request) -> tuple[str, bool]:
    """``(samesite, secure)`` for the SAML state cookie.

    Secure whenever the deployment is HTTPS — ``PUBLIC_BASE_URL`` or the request
    says so, or the operator marked the auth cookies Secure
    (``REFRESH_COOKIE_SECURE``, which is how the other auth cookies decide) —
    and then ``SameSite=None``, so the cookie rides the IdP's cross-site POST.
    Plain HTTP can't carry that (browsers reject a None cookie without Secure),
    so it falls back to Lax: a same-site IdP (a mock on another localhost port)
    still works, and a cross-site one needs the site served over HTTPS.
    """
    secure = (
        settings.refresh_cookie_secure
        or _base_url(request).startswith("https://")
        or request.url.scheme == "https"
    )
    return ("none" if secure else "lax"), secure


def _set_state_cookie(response: Response, request: Request, state: str) -> None:
    samesite, secure = _state_cookie_policy(request)
    response.set_cookie(
        key=SAML_STATE_COOKIE_NAME,
        value=state,
        max_age=int(_STATE_TTL.total_seconds()),
        httponly=True,
        secure=secure,
        samesite=samesite,
        path=SAML_STATE_COOKIE_PATH,
    )


def _clear_state_cookie(response: Response, request: Request) -> None:
    # Same attributes it was set with: a browser drops a SameSite=None deletion
    # that lacks Secure, which would leave the cookie behind.
    samesite, secure = _state_cookie_policy(request)
    response.delete_cookie(
        SAML_STATE_COOKIE_NAME,
        path=SAML_STATE_COOKIE_PATH,
        secure=secure,
        httponly=True,
        samesite=samesite,
    )


def _request_data(base: str, request: Request, post_data: dict) -> dict:
    """The ``python3-saml`` request dict, with host/scheme taken from
    ``base`` (the public origin) rather than the raw request. python3-saml
    reconstructs the current URL from these to validate the assertion's
    ``Destination`` against our ACS URL — behind the documented Caddy proxy the
    backend sees an internal host, so using the raw request would make every
    Destination check fail. The path still comes from the request (it *is* the
    ACS/login path)."""
    host = base.split("://", 1)[-1]
    return saml_utils.prepare_request_data(
        https=base.startswith("https"),
        host=host,
        path=request.url.path,
        get_data=dict(request.query_params),
        post_data=post_data,
    )


def _fail(reason: str, code: str) -> RedirectResponse:
    logger.warning("SAML login failed: %s", reason)
    return RedirectResponse(
        f"{_frontend_base()}/login?error={code}", status_code=status.HTTP_302_FOUND
    )


async def _enabled_provider(
    db: AsyncSession, slug: str
) -> tuple[IdentityProvider, SamlConfig] | None:
    """The enabled SAML provider behind ``slug`` with parsed config, or ``None``
    — the same ADR-0022 §6 re-parse guard the OIDC transport applies, so a
    drifted row is a logged skip indistinguishable from a disabled provider."""
    provider = await db.scalar(
        select(IdentityProvider).where(
            IdentityProvider.slug == slug,
            IdentityProvider.kind == "saml",
            IdentityProvider.enabled.is_(True),
        )
    )
    if provider is None:
        return None
    config = provider_config_or_none(provider)
    if not isinstance(config, SamlConfig):
        logger.warning(
            "saml provider %s has invalid stored config; treating as unavailable",
            slug,
        )
        return None
    return provider, config


def _first_attr(attributes: dict, name: str | None) -> str | None:
    """First value of a SAML attribute, by the exact Name the IdP sent (which
    the admin configures). SAML attribute values are always a list."""
    if not name:
        return None
    values = attributes.get(name)
    if isinstance(values, list) and values:
        first = values[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    return None


@router.get("/{slug}/login")
async def saml_login(
    slug: str,
    request: Request,
    return_to: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    loaded = await _enabled_provider(db, slug)
    if loaded is None:
        # A disabled or unknown provider is indistinguishable — no probing.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider"
        )
    provider, config = loaded
    base = _base_url(request)

    request_data = _request_data(base, request, post_data={})
    # RelayState is our single-use state token; the AuthnRequest id it produces
    # is what the ACS enforces InResponseTo against.
    state = secrets.token_urlsafe(32)
    try:
        auth = saml_utils.build_auth(provider, config, base, request_data)
        redirect_url = auth.login(return_to=state)
        request_id = auth.get_last_request_id()
    except Exception as exc:  # onelogin raises bare exceptions on bad settings
        return _fail(
            f"building AuthnRequest failed for {slug}: {exc}", "provider_unavailable"
        )

    # Opportunistic sweep so abandoned logins don't accumulate; the table is tiny.
    await db.execute(
        delete(AuthLoginState).where(AuthLoginState.expires_at < utcnow())
    )
    db.add(
        AuthLoginState(
            state=state,
            provider_id=provider.id,
            code_verifier=None,  # OIDC-only
            nonce=request_id,  # reused to carry the SAML AuthnRequest id
            return_to=_safe_return_to(return_to),
            created_at=utcnow(),
            expires_at=utcnow() + _STATE_TTL,
        )
    )
    await db.commit()
    redirect = RedirectResponse(redirect_url, status_code=status.HTTP_302_FOUND)
    # F3 browser-binding (GHSA-42m4): bind the login to THIS browser, so a
    # captured SAMLResponse+RelayState can't be POSTed into a victim's browser at
    # the ACS to fixate the attacker's session. Parity with OIDC/OAuth2, with
    # SAML's own cookie (see SAML_STATE_COOKIE_NAME).
    _set_state_cookie(redirect, request, state)
    return redirect


@router.post("/{slug}/acs", name="saml_acs")
async def saml_acs(
    slug: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    form = await request.form()
    saml_response = form.get("SAMLResponse")
    relay_state = form.get("RelayState")
    if not saml_response or not relay_state:
        return _fail("ACS missing SAMLResponse or RelayState", "invalid_response")
    relay_state = str(relay_state)

    # F3 browser-binding (GHSA-42m4): the browser presenting this response must
    # carry the httpOnly cookie set when IT began the login — the OIDC/OAuth2
    # parity the SAML ACS was missing. Single-use RelayState + InResponseTo stop
    # replay, not cross-browser session fixation (an attacker who completes the
    # IdP login as themselves, captures the still-valid SAMLResponse+RelayState,
    # and feeds it to a victim's browser). A refusal here leaves the cookie be:
    # a POST this browser didn't start mustn't cancel a login it did.
    if not sso_state_cookie_matches(
        request, relay_state, cookie_name=SAML_STATE_COOKIE_NAME
    ):
        if SAML_STATE_COOKIE_NAME not in request.cookies:
            # No cookie at all is what a deployment misconfiguration looks like
            # from here, rather than an injected response: an HTTPS site that
            # this process can't tell is HTTPS (behind a TLS proxy, with neither
            # PUBLIC_BASE_URL nor REFRESH_COOKIE_SECURE set) issues the cookie
            # as SameSite=Lax, and the IdP's cross-site POST never carries it.
            logger.warning(
                "SAML ACS for %s arrived without its state cookie; if every SAML "
                "login fails this way, set PUBLIC_BASE_URL to the site's https "
                "origin so the cookie is issued SameSite=None; Secure",
                slug,
            )
        return _fail(
            "SAML ACS state-cookie mismatch (cross-browser)", "invalid_state"
        )

    def fail(reason: str, code: str) -> RedirectResponse:
        # Past the binding check this login's state is spent, so every failure
        # from here on retires the cookie along with it.
        redirect = _fail(reason, code)
        _clear_state_cookie(redirect, request)
        return redirect

    # Consume the state row first: single-use, so a replayed POST finds nothing.
    # This is the CSRF check — a response we didn't initiate has no matching row.
    login_state = await db.get(AuthLoginState, relay_state)
    if login_state is None:
        return fail("unknown or already-used RelayState", "invalid_state")
    await db.delete(login_state)
    await db.commit()

    if ensure_aware_utc(login_state.expires_at) < utcnow():
        return fail("state expired", "expired")

    loaded = await _enabled_provider(db, slug)
    if loaded is None or loaded[0].id != login_state.provider_id:
        return fail(
            "provider disabled or mismatched between login and ACS",
            "provider_unavailable",
        )
    provider, config = loaded
    base = _base_url(request)

    request_data = _request_data(
        base,
        request,
        post_data={"SAMLResponse": str(saml_response), "RelayState": relay_state},
    )
    auth = saml_utils.build_auth(provider, config, base, request_data)
    try:
        # request_id ties the assertion to the AuthnRequest we issued
        # (InResponseTo); strict + wantAssertionsSigned enforce the signature
        # against idp_x509_cert before any content is trusted.
        auth.process_response(request_id=login_state.nonce)
    except Exception as exc:
        return fail(f"processing SAML response failed for {slug}: {exc}", "invalid_token")

    errors = auth.get_errors()
    if errors or not auth.is_authenticated():
        return fail(
            f"SAML validation failed for {slug}: {errors} "
            f"{auth.get_last_error_reason()}",
            "invalid_token",
        )

    # Solicited-only, enforced HERE rather than trusting a settings flag.
    # python3-saml validates InResponseTo only when the response *carries* one,
    # and it has no `rejectUnsolicitedResponsesWithInResponseTo` support (that's
    # a pysaml2 setting) — so an assertion with the attribute *absent* would sail
    # through every other check. Requiring the response's InResponseTo to equal
    # the AuthnRequest id we stored rejects both the missing (unsolicited /
    # IdP-initiated, out for v1 per ADR-0022 §4) and mismatched cases. This is
    # the SAML analogue of the OIDC `state` binding.
    if auth.get_last_response_in_response_to() != login_state.nonce:
        return fail(
            f"unsolicited or unmatched InResponseTo for {slug} "
            f"(got {auth.get_last_response_in_response_to()!r})",
            "invalid_token",
        )

    if not saml_utils.is_persistent_nameid_format(auth.get_nameid_format()):
        return fail(
            f"refusing non-persistent NameID format {auth.get_nameid_format()}",
            "invalid_token",
        )
    subject = auth.get_nameid()
    if not subject:
        return fail("assertion carried no NameID", "invalid_token")

    attributes = auth.get_attributes()
    email = _first_attr(attributes, config.email_attribute)
    if email is None and (auth.get_nameid_format() or "").endswith("emailAddress"):
        email = subject
    display_name = _first_attr(attributes, config.name_attribute)
    # display_name_from_claims reads name/preferred_username/given_name.
    claims = {"name": display_name, "email": email}

    # Imported here to keep the import graph acyclic (see routers/oidc).
    from auth.external_identity import IdentityRejected, resolve_identity

    try:
        user, created = await resolve_identity(
            db,
            provider,
            subject=subject,
            email=email,
            # SAML carries no standard email_verified; for a closed provider
            # (SAML is always closed, ADR-0022 §2) email trust comes from the
            # admin's email_is_authoritative flag, so this is deliberately False.
            email_verified=False,
            claims=claims,
        )
    except IdentityRejected as exc:
        return fail(
            f"admission policy rejected identity via {provider.slug}: {exc.code}",
            exc.code,
        )
    if not user.is_active:
        return fail(f"user {user.id} is banned", "account_disabled")

    await _issue_session(db, user, response)
    # Login done — retire the state-binding cookie (carried across on the redirect
    # below alongside the refresh cookie).
    _clear_state_cookie(response, request)

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
        "SAML login via %s: user=%s created=%s", provider.slug, user.id, created
    )
    return redirect


@router.get("/{slug}/metadata")
async def saml_metadata(
    slug: str, request: Request, db: AsyncSession = Depends(get_db)
) -> Response:
    """The SP metadata document. Public and served even when the provider is
    disabled: an administrator needs it to register the SP at the IdP *before*
    turning the provider on. It carries only the SP's own public descriptor."""
    provider = await db.scalar(
        select(IdentityProvider).where(
            IdentityProvider.slug == slug, IdentityProvider.kind == "saml"
        )
    )
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider"
        )
    config = provider_config_or_none(provider)
    if not isinstance(config, SamlConfig):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider configuration is incomplete",
        )
    xml, errors = saml_utils.sp_metadata_xml(provider, config, _base_url(request))
    if xml is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SP metadata invalid: {errors}",
        )
    return Response(content=xml, media_type="application/samlmetadata+xml")
