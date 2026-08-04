"""Schemas for identity-provider admin CRUD, all kinds (ADR-0022).

The provider row's ``config`` JSON is owned by a per-kind Pydantic model in the
:data:`PROVIDER_CONFIG_MODELS` registry. Adding a protocol means registering its
model here (plus a transport) — no schema migration. The registry is consulted
twice, deliberately (ADR-0022 §6):

- **at write** — a create/update refuses config that doesn't validate for its
  kind, and refuses ``enabled=True`` unless the effective config validates, so
  "enabled but half-configured" isn't reachable through the API;
- **at login** — the transport re-parses the stored config, so a row that
  drifted (a migration, a direct DB edit) is a logged skip, not a 500 in a
  user's face.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class OidcConfig(BaseModel):
    """Non-secret OIDC settings carried in ``IdentityProvider.config``.

    ``extra="forbid"`` so a typo'd key is a 400 at write time instead of a
    silently ignored setting.
    """

    model_config = ConfigDict(extra="forbid")

    # OIDC issuer; discovery is issuer + /.well-known/openid-configuration.
    issuer: str = Field(min_length=1, max_length=500)
    client_id: str = Field(min_length=1, max_length=500)
    scopes: str = Field(default="openid email profile", max_length=500)


class SamlConfig(BaseModel):
    """Non-secret SAML SP settings carried in ``IdentityProvider.config`` (#100,
    ADR-0022 §4). The one secret — the SP private key used to sign AuthnRequests —
    lives in ``IdentityProvider.secret``, not here; ``sp_x509_cert`` is public.

    ``extra="forbid"`` so a typo'd key is a 400, not a silently ignored setting.
    """

    model_config = ConfigDict(extra="forbid")

    # --- The IdP (all three required — the cert is what validates the assertion
    #     signature, and without it there is nothing to trust). ---
    idp_entity_id: str = Field(min_length=1, max_length=1000)
    # SSO endpoint for the HTTP-Redirect binding (where we send the AuthnRequest).
    idp_sso_url: str = Field(min_length=1, max_length=1000)
    # PEM or bare-base64 X.509; python3-saml accepts either.
    idp_x509_cert: str = Field(min_length=1, max_length=20_000)

    # --- The SP (us). ``sp_entity_id`` must match what's registered at the IdP;
    #     the ACS URL is derived server-side from PUBLIC_BASE_URL, not stored. ---
    sp_entity_id: str = Field(min_length=1, max_length=1000)
    # Optional public SP cert; present only when signing AuthnRequests (paired
    # with the private key in ``secret``). Signing the request is optional —
    # the load-bearing signature is the IdP's on the *assertion*, always required.
    sp_x509_cert: str | None = Field(default=None, max_length=20_000)

    # Persistent by default and the only value we accept: a transient NameID
    # changes each login and would JIT a fresh account every time (ADR-0022 §4,
    # the SAML analogue of "not the DN").
    nameid_format: Literal["persistent", "emailAddress"] = "persistent"

    # SAML attribute name (or OID) to read for each field. Email defaults to the
    # common friendly name; None falls back to the NameID when it's email-format.
    email_attribute: str | None = Field(default="email", max_length=200)
    name_attribute: str | None = Field(default="displayName", max_length=200)
    # NOTE (ADR-0022 §4 deviation, flagged not worked-around): python3-saml
    # validates Conditions timestamps exactly, with no clock-skew hook, so a
    # `clock_skew_seconds` field would be dead config. Left out until we add a
    # library-independent pre-check; tracked as a follow-up on #100.


# LDAP attribute descriptor (RFC 4512 short form). Deliberately narrow: these
# names are interpolated *unescaped* into the search filter and returned-
# attribute list, so the pattern is what keeps admin-supplied config from
# smuggling filter metacharacters (`*()\|&=`) past the RFC 4515 escaping that
# protects the user-supplied identifier. Numeric OIDs are excluded on purpose —
# every mainstream directory exposes a short name.
_LDAP_ATTRIBUTE_RE = r"^[A-Za-z][A-Za-z0-9-]{0,99}$"


class LdapConfig(BaseModel):
    """Non-secret LDAP settings carried in ``IdentityProvider.config`` (#101,
    ADR-0022 §5). The one secret — the service account's bind password — lives
    in ``IdentityProvider.secret``, not here.

    ``extra="forbid"`` so a typo'd key is a 400, not a silently ignored setting.
    """

    model_config = ConfigDict(extra="forbid")

    # ldaps://host[:port], or ldap://host[:port] combined with ``use_starttls``.
    # A plaintext bind is deliberately not expressible: the user's directory
    # password transits this server on every login (ADR-0022 §5).
    server_url: str = Field(min_length=1, max_length=500)
    use_starttls: bool = False

    # Service account that searches for the user's entry. Required — no
    # anonymous bind (ADR-0022 §5).
    bind_dn: str = Field(min_length=1, max_length=1000)
    base_dn: str = Field(min_length=1, max_length=1000)

    # Attribute matched against the submitted login identifier
    # (`sAMAccountName` / `userPrincipalName` on AD, `uid` elsewhere).
    search_attribute: str = Field(default="uid", pattern=_LDAP_ATTRIBUTE_RE)
    # The stable directory id used as the identity subject — `entryUUID`
    # (OpenLDAP/FreeIPA) or `objectGUID` (AD). Never the DN: a DN changes on an
    # OU move and would strand or re-mint the account (ADR-0022 §5).
    subject_attribute: str = Field(default="entryUUID", pattern=_LDAP_ATTRIBUTE_RE)
    email_attribute: str | None = Field(default="mail", pattern=_LDAP_ATTRIBUTE_RE)
    name_attribute: str | None = Field(default="displayName", pattern=_LDAP_ATTRIBUTE_RE)

    @model_validator(mode="after")
    def _tls_required(self) -> "LdapConfig":
        url = self.server_url.strip()
        if url.startswith("ldaps://"):
            return self
        if url.startswith("ldap://") and self.use_starttls:
            return self
        raise ValueError(
            "server_url must be ldaps://, or ldap:// with use_starttls enabled — "
            "a plaintext bind would send users' directory passwords in the clear"
        )


# kind -> config model. Registering a model here is what makes a kind creatable
# through the admin API (its transport must exist too, of course).
PROVIDER_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "oidc": OidcConfig,
    "saml": SamlConfig,
    "ldap": LdapConfig,
}

# Provider kinds whose login is a browser redirect (a "Sign in with…" button),
# as opposed to the local username/password form (LDAP, #101). Drives the
# public provider list so a non-redirect kind never grows a dead button.
REDIRECT_KINDS: frozenset[str] = frozenset({"oidc", "saml"})


def parse_provider_config(kind: str, config: dict) -> BaseModel:
    """Validate ``config`` against its kind's model.

    Raises ``ValueError`` for an unknown kind and ``pydantic.ValidationError``
    for a bad payload — callers decide whether that's a 400 (admin write) or a
    logged skip (login read). Callers distinguishing the two must catch
    ``ValidationError`` **first**: pydantic v2 makes it a ``ValueError``
    subclass, so the reverse order leaves the ValidationError branch dead.
    """
    model = PROVIDER_CONFIG_MODELS.get(kind)
    if model is None:
        raise ValueError(f"Unknown provider kind: {kind!r}")
    return model.model_validate(config or {})


def provider_config_or_none(provider) -> BaseModel | None:
    """The login-time re-parse (ADR-0022 §6): the stored config, or ``None`` if
    it no longer validates — the caller logs and treats the provider as absent."""
    try:
        return parse_provider_config(provider.kind, provider.config)
    except (ValueError, ValidationError):
        return None


class PublicProviderOut(BaseModel):
    """What an unauthenticated login page may know: enough to draw a button and
    build its login URL (``/api/auth/{kind}/{slug}/login``). Deliberately
    excludes all config — a login page has no use for an install's IdP topology,
    and not publishing it is free."""

    slug: str
    name: str
    kind: str


class ProviderOut(BaseModel):
    """Admin view. The secret is **write-only**: only whether one is set is
    ever returned, matching the SMTP-password precedent."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    posture: str
    name: str
    slug: str
    email_is_authoritative: bool
    config: dict
    enabled: bool
    created_at: datetime
    secret_set: bool = False
    # OIDC only: the exact value to register at the IdP. Computed server-side
    # because it depends on PUBLIC_BASE_URL, which the browser can't know — and
    # a mismatch here is the single most common reason an OIDC setup fails.
    redirect_uri: str = ""


class ProviderCreate(BaseModel):
    kind: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)
    # Lowercase URL-safe; validated in the router against a stricter pattern.
    slug: str = Field(min_length=1, max_length=60)
    posture: Literal["open", "closed"] = "open"
    email_is_authoritative: bool = False
    # Generous cap: an OIDC client secret is short, but a SAML SP private key
    # (PEM) runs to a few KB.
    secret: str | None = Field(default=None, max_length=10_000)
    config: dict = Field(default_factory=dict)
    enabled: bool = False


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    posture: Literal["open", "closed"] | None = None
    email_is_authoritative: bool | None = None
    # None leaves the stored secret untouched; "" clears it (public client).
    secret: str | None = Field(default=None, max_length=10_000)
    # Full replacement, not a merge — the admin form round-trips the whole
    # object, and merge semantics would make "remove a key" inexpressible.
    config: dict | None = None
    enabled: bool | None = None
