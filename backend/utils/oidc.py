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
- ``iss`` must equal the configured issuer, and ``aud`` must contain our
  ``client_id``;
- ``exp``/``iat`` are enforced by PyJWT;
- ``nonce`` must match the one minted for this login, which is what stops a
  token obtained elsewhere being replayed into our callback.
"""

from __future__ import annotations

import base64
import hashlib
import logging
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


async def discover(issuer: str) -> dict[str, Any]:
    """Fetch (and cache) the provider's discovery document."""
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
    # either misconfigured or an impersonation attempt; either way, refuse.
    advertised = document.get("issuer")
    if advertised and advertised.rstrip("/") != issuer.rstrip("/"):
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


async def validate_id_token(
    *,
    id_token: str,
    document: dict[str, Any],
    issuer: str,
    client_id: str,
    nonce: str,
) -> dict[str, Any]:
    """Verify the ID token's signature and claims, returning them."""
    key = await _signing_key(document["jwks_uri"], id_token)
    try:
        claims = jwt.decode(
            id_token,
            key=key,
            algorithms=ALLOWED_ID_TOKEN_ALGORITHMS,
            audience=client_id,
            issuer=issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.InvalidTokenError as exc:
        raise OidcError(f"invalid id_token: {exc}") from exc

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
