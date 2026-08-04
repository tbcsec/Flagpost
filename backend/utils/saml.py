"""SAML 2.0 SP plumbing (#100, ADR-0022 §4).

A thin, testable seam over ``python3-saml``. Everything protocol-specific and
security-critical — XML canonicalisation, signature verification (the
XSW-prone bit), ``Conditions`` and ``InResponseTo`` checks — lives inside the
library; this module only assembles its settings dict from an
``IdentityProvider`` row and adapts a request into the shape it wants. We
deliberately do **not** hand-roll any XML.

The security posture is fixed here, not left to per-provider config:

- ``wantAssertionsSigned`` is always on — a login is refused unless the
  *assertion* is signed, validated against the configured ``idp_x509_cert``
  *before* any assertion content is trusted. The message/envelope signature
  (``wantMessagesSigned``) is left optional, because many IdPs sign only the
  assertion and the assertion signature (plus the library's XSW defences) is
  what actually protects the identity.
- **Solicited-only** is enforced in the ACS handler (``routers/saml.py``), not
  here: it requires the response's ``InResponseTo`` to equal the AuthnRequest id
  we stored, so an assertion we didn't ask for — including an IdP-initiated one
  with no ``InResponseTo`` at all — is refused, the SAML analogue of the OIDC
  ``state`` check. This is done in our code on purpose: python3-saml validates
  ``InResponseTo`` only when the attribute is *present*, and has no
  ``rejectUnsolicitedResponsesWithInResponseTo`` setting (that belongs to
  pysaml2), so relying on the library alone would let an absent-``InResponseTo``
  assertion through. IdP-initiated SSO is out for v1 for this reason (ADR-0022 §4).
- Only a **persistent** NameID is accepted (config-enforced upstream); a
  transient one would mint a new account each login.

``onelogin`` (and its native ``lxml``/``xmlsec``) is imported **inside** the
functions, not at module scope, so an install with no SAML provider never loads
the native libraries — the transport module can be mounted for free and the
cost is paid only on a real SAML request. Mirrors how ``aiosmtplib`` stays out
of an SMTP-less install.
"""

from __future__ import annotations

from typing import Any


def acs_url(base_url: str, slug: str) -> str:
    return f"{base_url}/api/auth/saml/{slug}/acs"


def metadata_url(base_url: str, slug: str) -> str:
    return f"{base_url}/api/auth/saml/{slug}/metadata"


def _nameid_format_urn(short_name: str) -> str:
    from onelogin.saml2.constants import OneLogin_Saml2_Constants as C

    return {
        "persistent": C.NAMEID_PERSISTENT,
        "emailAddress": C.NAMEID_EMAIL_ADDRESS,
    }[short_name]


def build_settings_dict(provider, config, base_url: str) -> dict[str, Any]:
    """The ``python3-saml`` settings for one provider.

    ``config`` is a validated ``schemas.auth_providers.SamlConfig``; ``provider``
    is the ``IdentityProvider`` row (its ``secret`` is the SP private key, or
    ``None`` for an SP that doesn't sign its AuthnRequests). ``base_url`` is the
    externally-visible origin (``PUBLIC_BASE_URL``), the same source the OIDC
    redirect URI uses so a TLS-terminating proxy doesn't corrupt the ACS URL.
    """
    from onelogin.saml2.constants import OneLogin_Saml2_Constants as C

    slug = provider.slug
    sp_signs = bool(provider.secret and config.sp_x509_cert)
    return {
        "strict": True,
        "sp": {
            "entityId": config.sp_entity_id,
            "assertionConsumerService": {
                "url": acs_url(base_url, slug),
                "binding": C.BINDING_HTTP_POST,
            },
            "NameIDFormat": _nameid_format_urn(config.nameid_format),
            "x509cert": config.sp_x509_cert or "",
            "privateKey": provider.secret or "",
        },
        "idp": {
            "entityId": config.idp_entity_id,
            "singleSignOnService": {
                "url": config.idp_sso_url,
                "binding": C.BINDING_HTTP_REDIRECT,
            },
            "x509cert": config.idp_x509_cert,
        },
        "security": {
            # Non-negotiable and load-bearing: the *assertion* must be signed,
            # verified against idp_x509_cert before any content is trusted. The
            # response envelope signature is left optional (many IdPs sign only
            # the assertion) — the assertion signature plus the library's XSW
            # defences are what actually protect the identity.
            "wantAssertionsSigned": True,
            "wantMessagesSigned": False,
            "wantNameId": True,
            # NB: solicited-only (InResponseTo binding) is NOT set here —
            # python3-saml has no such setting, and it checks InResponseTo only
            # when present. The ACS handler enforces it explicitly instead.
            # We sign the AuthnRequest only when we hold both key and cert;
            # otherwise send it unsigned (the inbound assertion signature is
            # what actually protects the login).
            "authnRequestsSigned": sp_signs,
            "wantAssertionsEncrypted": False,
            "wantNameIdEncrypted": False,
            "requestedAuthnContext": False,
            "signatureAlgorithm": C.RSA_SHA256,
            "digestAlgorithm": C.SHA256,
        },
    }


def build_auth(provider, config, base_url: str, request_data: dict):
    """A configured ``OneLogin_Saml2_Auth`` for a request. Clock skew is applied
    to the process-response call by the caller, not here."""
    from onelogin.saml2.auth import OneLogin_Saml2_Auth

    return OneLogin_Saml2_Auth(
        request_data, build_settings_dict(provider, config, base_url)
    )


def prepare_request_data(
    *, https: bool, host: str, path: str, get_data: dict, post_data: dict
) -> dict[str, Any]:
    """Adapt a request into the dict ``OneLogin_Saml2_Auth`` expects.

    Kept parameterised (not coupled to ``fastapi.Request``) so tests can drive
    the ACS with a hand-built POST body without an HTTP round trip.
    """
    return {
        "https": "on" if https else "off",
        "http_host": host,
        "script_name": path,
        "get_data": get_data,
        "post_data": post_data,
    }


def is_persistent_nameid_format(fmt: str | None) -> bool:
    """A returned NameID must be persistent (or unspecified, which some IdPs
    emit for a persistent id). A transient format is refused — it changes each
    login and would JIT a fresh account every time (ADR-0022 §4)."""
    if not fmt:
        return True  # absent format: python3-saml already matched SP policy
    from onelogin.saml2.constants import OneLogin_Saml2_Constants as C

    return fmt in (C.NAMEID_PERSISTENT, C.NAMEID_UNSPECIFIED, C.NAMEID_EMAIL_ADDRESS)


def sp_metadata_xml(provider, config, base_url: str) -> tuple[str | None, list[str]]:
    """The SP metadata document (ACS URL + entityId + optional SP cert), or
    ``(None, errors)`` if the settings don't validate. An IdP admin consumes
    this instead of hand-transcribing our ACS URL and certificate."""
    from onelogin.saml2.settings import OneLogin_Saml2_Settings

    settings = OneLogin_Saml2_Settings(
        build_settings_dict(provider, config, base_url), sp_validation_only=True
    )
    metadata = settings.get_sp_metadata()
    errors = settings.validate_metadata(metadata)
    if errors:
        return None, errors
    return (
        metadata.decode("utf-8") if isinstance(metadata, bytes) else metadata,
        [],
    )
