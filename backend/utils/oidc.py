"""OIDC protocol mechanics (ADR-0021, issue #58).

Everything that talks to an identity provider lives here so the router stays a
thin HTTP shell: discovery, JWKS handling, the token exchange, and ID-token
validation.

**Every outbound URL is admin-supplied**, which makes this the same class of
egress risk as automation webhooks (§5.4, ADR-0013) — an operator who can add a
provider could otherwise point discovery at `169.254.169.254` and read the
response through an error message. The SSRF checks from
``utils.webhook_security`` are reused rather than reimplemented, tightened to
**https-only** since an OIDC issuer must be https per the spec.

Validation is deliberately strict, because every shortcut here is a real
vulnerability rather than a bug:

- the signature is checked against the provider's JWKS (RS256/ES256 family
  only — never ``none``, and never an HMAC algorithm, which would let the
  *public* key double as a signing secret);
- ``iss`` must equal the configured issuer — or, for a tenant-templated
  multi-tenant Entra provider, the token's own ``tid`` substituted into the
  configured template (ADR-0032, #194) — and ``aud`` must contain our
  ``client_id``;
- ``exp``/``iat`` are enforced by PyJWT;
- ``nonce`` must match the one minted for this login, which is what stops a
  token obtained elsewhere being replayed into our callback.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt
from jwt import PyJWKSet

from config import settings
from utils.webhook_security import _ip_is_blocked, _resolve_host

logger = logging.getLogger("oidc")

# ID tokens are asymmetrically signed in practice. Excluding the HMAC family is
# not stylistic: with HS*, the verification key is the *shared secret*, so
# accepting it alongside a published JWKS would let an attacker sign a token
# with the provider's public key.
ALLOWED_ID_TOKEN_ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]

# Tenant-templated issuer validation for multi-tenant Entra (ADR-0032, #194).
# ``TENANT_ID_PLACEHOLDER`` is Entra's own spelling — its ``common`` discovery
# document advertises the literal ``…/{tenantid}/v2.0`` as its issuer, and an
# admin's ``issuer_template`` must use the same token so the two match. Shared
# with ``schemas.auth_providers`` (write-time validation) so the placeholder a
# template must carry, and the GUID a token's ``tid`` must be, can't drift from
# what login substitutes. The GUID shape is load-bearing: it pins the tenant slot
# of the substituted issuer so a token can't smuggle a foreign host or path
# through it (see ``_validate_tenant_issuer``).
TENANT_ID_PLACEHOLDER = "{tenantid}"
_TENANT_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

_DISCOVERY_TTL_SECONDS = 3600
_JWKS_TTL_SECONDS = 3600
_HTTP_TIMEOUT = 10.0

# (document, fetched_at) keyed by issuer / jwks_uri.
_discovery_cache: dict[str, tuple[dict[str, Any], float]] = {}
_jwks_cache: dict[str, tuple[PyJWKSet, float]] = {}


class OidcError(Exception):
    """A provider interaction failed. The message is safe to log but is never
    returned verbatim to the browser — see the router's error handling."""


async def validate_issuer_url(url: str) -> None:
    """Refuse anything but a public https endpoint (ADR-0021).

    Re-resolved on every fetch rather than trusted from configuration time, so
    DNS that changes after a provider is saved is re-checked. Note the same
    resolve-then-connect TOCTOU that §15 records for webhooks applies here.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        if settings.oidc_allow_insecure_issuers:
            logger.warning(
                "allowing non-https OIDC issuer %s — OIDC_ALLOW_INSECURE_ISSUERS "
                "is on. This is a local-development affordance and must never be "
                "set in production.",
                url,
            )
        else:
            raise OidcError("issuer must be https")
    host = parts.hostname
    if not host:
        raise OidcError("issuer has no host")
    if settings.oidc_allow_insecure_issuers:
        return

    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        addresses = await _resolve_host(host, port)
    except Exception as exc:  # noqa: BLE001 — unresolvable → can't prove safe
        raise OidcError(f"issuer host {host!r} does not resolve") from exc
    for address in addresses:
        import ipaddress

        if _ip_is_blocked(ipaddress.ip_address(address)):
            raise OidcError(f"issuer host {host!r} resolves to a blocked address")


async def _get_json(url: str) -> dict[str, Any]:
    await validate_issuer_url(url)
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT, follow_redirects=False
    ) as client:
        response = await client.get(url)
    if response.status_code != 200:
        raise OidcError(f"GET {url} returned {response.status_code}")
    return response.json()


async def discover(issuer: str, *, issuer_template: str | None = None) -> dict[str, Any]:
    """Fetch (and cache) the provider's discovery document.

    ``issuer_template`` is set only for a tenant-templated provider (multi-tenant
    Entra, ADR-0032): its ``common``/``organizations`` discovery document
    advertises the *template* (``…/{tenantid}/v2.0``) rather than the configured
    authority (``…/common/v2.0``), so both are accepted. For every other provider
    it is ``None`` and the advertised issuer must equal the configured one
    exactly, unchanged.
    """
    now = time.monotonic()
    cached = _discovery_cache.get(issuer)
    if cached and now - cached[1] < _DISCOVERY_TTL_SECONDS:
        return cached[0]

    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    document = await _get_json(url)
    for required in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not document.get(required):
            raise OidcError(f"discovery document is missing {required}")
    # A provider that advertises a different issuer than the one configured is
    # either misconfigured or an impersonation attempt; either way, refuse. A
    # tenant-templated provider legitimately advertises the template verbatim.
    advertised = document.get("issuer")
    if advertised:
        allowed = {issuer.rstrip("/")}
        if issuer_template is not None:
            allowed.add(issuer_template.rstrip("/"))
        if advertised.rstrip("/") not in allowed:
            raise OidcError("discovery issuer does not match the configured issuer")

    _discovery_cache[issuer] = (document, now)
    return document


async def _get_jwks(jwks_uri: str, *, force: bool = False) -> PyJWKSet:
    now = time.monotonic()
    cached = _jwks_cache.get(jwks_uri)
    if cached and not force and now - cached[1] < _JWKS_TTL_SECONDS:
        return cached[0]
    key_set = PyJWKSet.from_dict(await _get_json(jwks_uri))
    _jwks_cache[jwks_uri] = (key_set, now)
    return key_set


async def _signing_key(jwks_uri: str, token: str):
    """Find the JWKS key matching the token's ``kid``, refetching once on a miss
    so a key rotation doesn't require a restart."""
    kid = jwt.get_unverified_header(token).get("kid")
    for attempt in (False, True):
        key_set = await _get_jwks(jwks_uri, force=attempt)
        for key in key_set.keys:
            if kid is None or key.key_id == kid:
                return key.key
    raise OidcError("no matching signing key in the provider's JWKS")


def generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for PKCE S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


async def exchange_code(
    *,
    document: dict[str, Any],
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str | None,
    code_verifier: str,
) -> dict[str, Any]:
    """Swap the authorization code for tokens at the provider's token endpoint."""
    token_endpoint = document["token_endpoint"]
    await validate_issuer_url(token_endpoint)

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    # Confidential clients authenticate with the secret; a public client
    # (no secret configured) relies on PKCE alone, which is the correct
    # arrangement for providers that don't issue one.
    auth = (client_id, client_secret) if client_secret else None
    if client_secret:
        data.pop("client_id")

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT, follow_redirects=False
    ) as client:
        response = await client.post(token_endpoint, data=data, auth=auth)
    if response.status_code != 200:
        raise OidcError(f"token endpoint returned {response.status_code}")
    payload = response.json()
    if "id_token" not in payload:
        raise OidcError("token response contained no id_token")
    return payload


def _validate_tenant_issuer(claims: dict[str, Any], issuer_template: str) -> None:
    """Validate a multi-tenant id_token's ``iss`` against its own ``tid`` (ADR-0032).

    The multi-tenant Entra authorities (``common`` / ``organizations``) mint a
    token whose ``iss`` carries the *signing-in user's* tenant GUID, so there is
    no single fixed issuer to string-match. Instead the token's own ``tid`` claim
    — constrained to a GUID — is substituted into the admin-validated template and
    ``iss`` must equal the result exactly.

    Constraining ``tid`` to a GUID is what keeps this safe: the template's host and
    path are fixed at write time (``schemas.auth_providers``), and a GUID tenant
    slot means the substituted issuer's shape can't be bent by the token, so this
    binds ``iss`` to the tenant that actually signed the token without trusting any
    claim for *authorization* (ADR-0021 — admission stays the email allowlist).
    """
    tid = claims.get("tid")
    if not isinstance(tid, str) or not _TENANT_ID_RE.match(tid):
        raise OidcError("id_token has no GUID tid claim for a tenant-templated issuer")
    expected = issuer_template.replace(TENANT_ID_PLACEHOLDER, tid)
    if claims.get("iss") != expected:
        raise OidcError("id_token iss does not match the tenant-substituted issuer")


async def validate_id_token(
    *,
    id_token: str,
    document: dict[str, Any],
    issuer: str,
    client_id: str,
    nonce: str,
    issuer_template: str | None = None,
) -> dict[str, Any]:
    """Verify the ID token's signature and claims, returning them.

    For an ordinary provider (``issuer_template is None``) ``iss`` must equal the
    configured ``issuer`` exactly and PyJWT enforces it. For a tenant-templated
    provider (multi-tenant Entra, ADR-0032) ``iss`` is instead validated against
    the token's own ``tid`` substituted into the template (``_validate_tenant_issuer``);
    signature, ``aud``, ``exp``/``iat`` and ``nonce`` are checked identically either
    way. ``iss`` is required-present in both branches — only its *value* check moves.
    """
    key = await _signing_key(document["jwks_uri"], id_token)
    decode_kwargs: dict[str, Any] = {
        "key": key,
        "algorithms": ALLOWED_ID_TOKEN_ALGORITHMS,
        "audience": client_id,
        "options": {"require": ["exp", "iat", "iss", "aud", "sub"]},
    }
    # Templated providers can't use PyJWT's exact-string issuer match; their `iss`
    # is value-checked by hand below, after the signature is verified.
    if issuer_template is None:
        decode_kwargs["issuer"] = issuer
    try:
        claims = jwt.decode(id_token, **decode_kwargs)
    except jwt.InvalidTokenError as exc:
        raise OidcError(f"invalid id_token: {exc}") from exc

    if issuer_template is not None:
        _validate_tenant_issuer(claims, issuer_template)

    # Binds the token to *this* login attempt. Without it, an ID token obtained
    # through any other flow for the same client could be replayed here.
    if claims.get("nonce") != nonce:
        raise OidcError("id_token nonce does not match")
    return claims


async def fetch_userinfo(
    document: dict[str, Any], access_token: str
) -> dict[str, Any]:
    """Best-effort userinfo lookup, used only to fill an email the ID token
    didn't carry. A failure here is not fatal — the caller falls back to
    prompting the user."""
    endpoint = document.get("userinfo_endpoint")
    if not endpoint or not access_token:
        return {}
    try:
        await validate_issuer_url(endpoint)
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT, follow_redirects=False
        ) as client:
            response = await client.get(
                endpoint, headers={"Authorization": f"Bearer {access_token}"}
            )
        if response.status_code == 200:
            return response.json()
    except Exception:  # noqa: BLE001 — optional enrichment, never fatal
        logger.warning("userinfo lookup failed", exc_info=True)
    return {}
