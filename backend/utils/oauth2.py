"""Plain-OAuth2 protocol mechanics (ADR-0033, issue #193).

The sibling of ``utils/oidc.py`` for providers that speak OAuth 2.0 but not
OpenID Connect — GitHub and Discord being the motivating pair. The difference
that shapes this whole module: **there is no ID token**. OIDC hands us a signed
assertion we verify offline; plain OAuth2 hands us an opaque access token, and
identity comes from *calling the provider back* with it.

That makes the trust chain different, and worth stating plainly:

- we exchange the code at the configured ``token_url`` over TLS, authenticating
  with our own ``client_secret``;
- we present the resulting access token to the configured ``userinfo_url`` over
  TLS and treat that response as the identity.

There is nothing to check a signature against, so the security rests on TLS and
on **every leg being server-to-server**. The platform must never accept an
access token or a profile payload from the browser — that is the classic
OAuth2-as-authentication flaw (a token minted for a different client replayed
into our callback). ``state`` remains the CSRF control, single-use, exactly as
in the OIDC transport.

Because the endpoint URLs are admin-supplied, they carry the same egress risk as
automation webhooks (§5.4, ADR-0013) and OIDC issuers (ADR-0021); every outbound
URL here goes through the same https-only, SSRF-blocking check rather than a
second implementation of it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from utils import oidc as oidc_utils
from utils.oidc import OidcError

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a runtime import cycle
    from schemas.auth_providers import OAuth2Config

logger = logging.getLogger("oauth2")

_HTTP_TIMEOUT = 10.0

# GitHub's REST API rejects requests that arrive without a User-Agent, so this
# is a functional requirement rather than politeness.
_USER_AGENT = "Flagpost"

# Sent on both calls: GitHub's token endpoint otherwise answers
# form-urlencoded, which would parse as garbage rather than fail loudly.
_JSON_HEADERS = {"Accept": "application/json", "User-Agent": _USER_AGENT}


class OAuth2Error(Exception):
    """A provider interaction failed. Safe to log; never returned verbatim to
    the browser — see the transport's error handling."""


async def validate_endpoint_url(url: str) -> None:
    """Refuse anything but a public https endpoint.

    Delegates to the OIDC issuer check rather than reimplementing it: the rule
    (https-only, resolve the host, refuse private/link-local addresses,
    re-checked on every call because DNS can change) is identical, and one
    implementation means one place to harden. Called through the module so the
    network seam stays monkeypatchable in tests.
    """
    try:
        await oidc_utils.validate_issuer_url(url)
    except OidcError as exc:
        raise OAuth2Error(str(exc)) from exc


async def exchange_code(
    *,
    token_url: str,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str | None,
    code_verifier: str | None = None,
) -> str:
    """Swap the authorization code for an access token, which is returned.

    Credentials go in the request **body** rather than HTTP Basic. Both target
    providers accept that form, and it is the more widely supported of the two
    across arbitrary OAuth2 servers — the OIDC transport's preference for Basic
    follows from OIDC's stricter conformance expectations, which don't apply here.

    The access token is returned to the caller for one immediate userinfo call
    and is deliberately never persisted (ADR-0033): Flagpost wants an identity at
    login, not a credential vault.
    """
    await validate_endpoint_url(token_url)

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret
    if code_verifier:
        data["code_verifier"] = code_verifier

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT, follow_redirects=False
    ) as client:
        response = await client.post(token_url, data=data, headers=_JSON_HEADERS)
    if response.status_code != 200:
        raise OAuth2Error(f"token endpoint returned {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise OAuth2Error("token endpoint did not return JSON") from exc
    if not isinstance(payload, dict):
        raise OAuth2Error("token endpoint returned a non-object payload")
    # GitHub reports a bad/expired code as HTTP **200** with an `error` key, so
    # a status-only check would sail past it and then fail confusingly at
    # userinfo with an empty token.
    if payload.get("error"):
        raise OAuth2Error(f"token endpoint returned error {payload['error']!r}")
    token = payload.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise OAuth2Error("token response contained no access_token")
    return token


async def fetch_json(url: str, access_token: str) -> Any:
    """GET a JSON document from the provider as the authenticated user."""
    await validate_endpoint_url(url)
    headers = {**_JSON_HEADERS, "Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT, follow_redirects=False
    ) as client:
        response = await client.get(url, headers=headers)
    if response.status_code != 200:
        raise OAuth2Error(f"GET {url} returned {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise OAuth2Error(f"GET {url} did not return JSON") from exc


def subject_from_profile(profile: dict, field: str) -> str:
    """The provider's stable user id, as a string (ADR-0021's sub-first rule).

    Coerced from a number because GitHub's ``id`` is a JSON integer while
    ``UserExternalIdentity.subject`` is text; ``bool`` is excluded explicitly
    since it is an ``int`` subclass in Python and ``str(True)`` would be a
    catastrophically non-unique subject.
    """
    value = profile.get(field)
    if isinstance(value, bool) or value is None:
        raise OAuth2Error(f"userinfo has no usable {field!r} to use as the subject")
    if isinstance(value, (str, int)):
        subject = str(value).strip()
        if subject:
            return subject
    raise OAuth2Error(f"userinfo has no usable {field!r} to use as the subject")


def _string_field(profile: dict, field: str | None) -> str | None:
    """A trimmed string from the profile, or None — tolerant of the nulls these
    APIs routinely return (GitHub's ``name`` is null for most accounts)."""
    if not field:
        return None
    value = profile.get(field)
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _claim_is_true(value: object) -> bool:
    """Strictly interpret a verified-flag claim.

    Mirrors the OIDC transport's helper for the same reason: ``bool("false")``
    is ``True``, so a provider serialising the flag as a string would mark every
    user verified — and this gates both existing-account linking and the
    email-domain admission check (#118).
    """
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def select_primary_verified_email(entries: Any) -> str | None:
    """The primary, verified address from a GitHub-shaped email list.

    ``GET /user/emails`` returns ``[{email, primary, verified}, ...]``. Only an
    address that is **both** primary and verified is trusted: "verified" alone
    proves the user controls the mailbox, but taking a non-primary address would
    silently pick an identity the user did not present as theirs, and the
    ADR-0022 §3 rule is about believing an address enough to link it to an
    existing local account. No match returns ``None``, and the caller falls back
    to the profile address as *unverified* — display-only, never a link key.
    """
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        email = entry.get("email")
        if not isinstance(email, str) or not email.strip():
            continue
        if _claim_is_true(entry.get("verified")) and _claim_is_true(
            entry.get("primary")
        ):
            return email.strip()
    return None


async def fetch_identity(
    config: OAuth2Config, access_token: str
) -> tuple[str, str | None, bool, dict]:
    """Return ``(subject, email, email_verified, claims)`` for a logged-in user.

    One userinfo call, plus a second call to ``emails_url`` when the provider
    keeps verified addresses on a separate endpoint (GitHub). ``email_verified``
    is only ever true when the provider actually said so — an unset
    ``email_verified_field`` with no ``emails_url`` means we have no evidence,
    so the answer is ``False`` rather than an optimistic default (ADR-0022 §3).
    """
    profile = await fetch_json(config.userinfo_url, access_token)
    if not isinstance(profile, dict):
        raise OAuth2Error("userinfo did not return a JSON object")

    subject = subject_from_profile(profile, config.subject_field)
    email = _string_field(profile, config.email_field)
    email_verified = False

    if config.emails_url:
        # GitHub: the profile address is often null or unverified, and the
        # authoritative set lives here. A failure is fatal rather than a silent
        # downgrade to "unverified" — the provider is configured to have this
        # endpoint, so not reaching it means we don't know what we're claiming.
        verified_email = select_primary_verified_email(
            await fetch_json(config.emails_url, access_token)
        )
        if verified_email:
            email, email_verified = verified_email, True
    elif config.email_verified_field:
        email_verified = _claim_is_true(profile.get(config.email_verified_field))

    # Normalized on top of the raw profile so `display_name_from_claims` finds a
    # usable name under the key it already looks for, while the untouched
    # provider payload stays available to whatever reads claims later.
    claims = {
        **profile,
        "sub": subject,
        "email": email,
        "name": _string_field(profile, config.name_field),
    }
    return subject, email, email_verified, claims
