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
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from utils.oidc import TENANT_ID_PLACEHOLDER

# A syntactically valid tenant GUID, used only to probe an ``issuer_template``'s
# shape at write time (OidcConfig below) — never a real tenant.
_SAMPLE_TENANT_ID = "00000000-0000-0000-0000-000000000000"


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

    # Multi-tenant issuer validation (ADR-0032, #194). None for every ordinary
    # provider — single-tenant Entra included — which keeps its issuer checks
    # byte-for-byte as strict as before. When set, this provider's id_token
    # ``iss`` is validated against this template with the token's own ``tid``
    # substituted for ``{tenantid}`` (Entra's own placeholder) rather than by
    # exact string match — the standard fix for the multi-tenant Entra
    # authorities (``common`` / ``organizations``), whose ``iss`` carries the
    # signing-in user's tenant GUID. ``issuer`` stays the discovery authority
    # (``…/common/v2.0``).
    #
    # Distinct from ``ProviderPresetOut.issuer_template`` despite the shared
    # name: that one is *form-fill* (``{tenant_id}`` resolved from an admin param
    # at setup to produce a fixed ``issuer``); this one is *validation*
    # (``{tenantid}`` resolved from the token at every login).
    issuer_template: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _issuer_template_is_safe(self) -> "OidcConfig":
        """Keep a set template from becoming an open redirect or a split-origin
        trust (ADR-0032). The placeholder must resolve into the *path* of an
        https URL on the **same host** as the discovery authority — never into
        the host itself, which would let a login be pointed at an attacker's
        origin, and never a different host than discovery is fetched from."""
        template = self.issuer_template
        if template is None:
            return self
        if template.count(TENANT_ID_PLACEHOLDER) != 1:
            raise ValueError(
                f"issuer_template must contain exactly one {TENANT_ID_PLACEHOLDER} placeholder"
            )
        probe = urlsplit(template.replace(TENANT_ID_PLACEHOLDER, _SAMPLE_TENANT_ID))
        if probe.scheme != "https":
            raise ValueError("issuer_template must be https")
        host = probe.hostname or ""
        if not host or _SAMPLE_TENANT_ID in host:
            raise ValueError(
                "issuer_template placeholder must be in the path, not the host"
            )
        if urlsplit(self.issuer).hostname != host:
            raise ValueError("issuer_template host must match the issuer host")
        return self


# Field naming an attribute inside the provider's userinfo JSON (OAuth2Config's
# claim map). Deliberately narrow — these are looked up as plain dict keys, and
# a tight charset keeps a typo'd or hostile manifest from naming something
# unexpected. Dots are allowed for providers that nest under one level.
_JSON_FIELD_RE = r"^[A-Za-z_][A-Za-z0-9_.-]{0,99}$"


class OAuth2Config(BaseModel):
    """Non-secret settings for a plain-OAuth2 (non-OIDC) provider (#193, ADR-0033).

    Unlike OIDC there is no discovery document, so all three endpoints are given
    explicitly, and no ID token, so identity is read out of the provider's
    userinfo JSON by the **claim map** below. The one secret — the OAuth client
    secret — lives in ``IdentityProvider.secret``, not here.

    ``extra="forbid"`` so a typo'd key is a 400, not a silently ignored setting.
    """

    model_config = ConfigDict(extra="forbid")

    # --- The provider's three endpoints. https + SSRF checks are applied at
    #     write time and again on every call (utils.oauth2.validate_endpoint_url),
    #     not here, so a dev-only insecure issuer stays expressible exactly as it
    #     is for OIDC. ---
    authorize_url: str = Field(min_length=1, max_length=500)
    token_url: str = Field(min_length=1, max_length=500)
    userinfo_url: str = Field(min_length=1, max_length=500)
    client_id: str = Field(min_length=1, max_length=500)
    # No mandatory scope (OAuth2 has no `openid`); what's needed is per-provider,
    # so the presets carry it and a hand-configured provider may legitimately
    # send none.
    scopes: str = Field(default="", max_length=500)

    # --- Claim map: which userinfo JSON keys carry identity. ---
    # The provider's own stable user id — GitHub's numeric `id`, Discord's
    # snowflake. Never the email (ADR-0021 sub-first).
    subject_field: str = Field(default="id", pattern=_JSON_FIELD_RE)
    email_field: str | None = Field(default="email", pattern=_JSON_FIELD_RE)
    name_field: str | None = Field(default="name", pattern=_JSON_FIELD_RE)
    # A boolean field asserting the address is verified (Discord: `verified`).
    # Unset means the provider gives us no such assertion, so the address is
    # treated as unverified — never optimistically trusted (ADR-0022 §3).
    email_verified_field: str | None = Field(default=None, pattern=_JSON_FIELD_RE)
    # Providers that keep verified addresses on a separate list endpoint
    # (GitHub `/user/emails` → [{email, primary, verified}, …]). When set, the
    # primary verified address wins over the profile one.
    emails_url: str | None = Field(default=None, max_length=500)

    # PKCE is defence in depth here rather than the primary control (`state` +
    # client_secret + an exact redirect_uri are), and this kind must work against
    # arbitrary servers — some reject unrecognised parameters, and GitHub's OAuth
    # Apps simply ignore them. Off by default; presets opt in where supported.
    use_pkce: bool = False

    @model_validator(mode="after")
    def _endpoints_are_urls(self) -> "OAuth2Config":
        """Catch a typo'd endpoint at write time rather than at someone's first
        login. Shape only — scheme-and-host; the https requirement and the SSRF
        blocklist are enforced on every outbound call."""
        for name in ("authorize_url", "token_url", "userinfo_url", "emails_url"):
            value = getattr(self, name)
            if value is None:
                continue
            parts = urlsplit(value)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise ValueError(f"{name} must be an absolute http(s) URL")
        return self


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
    "oauth2": OAuth2Config,
    "saml": SamlConfig,
    "ldap": LdapConfig,
}

# Provider kinds whose login is a browser redirect (a "Sign in with…" button),
# as opposed to the local username/password form (LDAP, #101). Drives the
# public provider list so a non-redirect kind never grows a dead button.
REDIRECT_KINDS: frozenset[str] = frozenset({"oidc", "oauth2", "saml"})


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
    # Well-known-IdP marker ("google" / "microsoft") so the login page can draw
    # the right button art. Derived server-side from the stored issuer at read
    # time (utils/provider_presets.brand_for_provider, ADR-0024) — it reveals
    # nothing the branded button itself wouldn't.
    brand: str | None = None


class PresetParamOut(BaseModel):
    """One admin-supplied input a preset needs to resolve its issuer template
    (Microsoft's tenant id). ``pattern`` is a client-side hint only — the
    resolved issuer still goes through the normal write-time OIDC validation."""

    key: str
    label: str
    placeholder: str
    pattern: str
    # Canonicalization applied to the value before it is substituted into the
    # issuer template. Entra lowercases the tenant GUID in its discovery
    # document and id_token ``iss``, and the issuer-equality checks in
    # ``utils/oidc.py`` are case-sensitive — an uppercase paste would save
    # fine and then fail at first sign-in, the exact silent misconfiguration
    # presets exist to prevent.
    normalize: Literal["lowercase"] | None = None
    help: str


class OAuth2PresetOut(BaseModel):
    """The ``oauth2``-kind config a preset prefills (#193, ADR-0033).

    A plain-OAuth2 provider has no issuer to derive anything from, so where an
    OIDC preset ships one URL this ships the whole endpoint set plus the claim
    map. Mirrors the non-secret half of :class:`OAuth2Config` — the client id
    and secret still come from the administrator's own registered app, never
    from a preset (ADR-0024).
    """

    authorize_url: str
    token_url: str
    userinfo_url: str
    scopes: str
    subject_field: str
    email_field: str | None = None
    name_field: str | None = None
    email_verified_field: str | None = None
    emails_url: str | None = None
    use_pkce: bool = False


class ProviderPresetOut(BaseModel):
    """A built-in provider preset (ADR-0024): form-prefill for the admin
    "add provider" flow, served from ``utils/provider_presets``. Configuration
    defaults only, never credentials — each install registers its own upstream
    OAuth app."""

    id: str
    name: str
    kind: str
    # OIDC presets only. Exactly one of the two is set: a fixed issuer, or a
    # template whose ``{key}`` placeholders are filled from ``params``.
    issuer: str | None = None
    issuer_template: str | None = None
    # Multi-tenant only (ADR-0032): the value the create form drops into the new
    # provider's ``config.issuer_template`` — the pattern the id_token ``iss`` is
    # validated against at *login*. Distinct from ``issuer_template`` above, which
    # is *form-fill* resolved from ``params`` into ``config.issuer`` at *setup*.
    # None for every single-value preset.
    config_issuer_template: str | None = None
    params: list[PresetParamOut] = Field(default_factory=list)
    # ``oauth2``-kind presets only: the endpoint set + claim map, since a plain
    # OAuth2 provider has no issuer to derive them from (#193, ADR-0033).
    oauth2: OAuth2PresetOut | None = None
    scopes: str
    default_slug: str
    posture: str
    setup_url: str
    notes: str

    @model_validator(mode="after")
    def _config_block_matches_kind(self) -> "ProviderPresetOut":
        """Each kind carries exactly the config block it can actually use.

        A bad future catalog entry should fail at the route, loudly, rather than
        ship as a setup card that does nothing — the frontend gates the create
        form on having something to prefill.
        """
        if self.kind == "oidc":
            # Both set is ambiguous; neither is a dead card.
            if (self.issuer is None) == (self.issuer_template is None):
                raise ValueError(
                    "exactly one of issuer / issuer_template must be set"
                )
            if self.oauth2 is not None:
                raise ValueError("oauth2 config block is not valid on an oidc preset")
            return self
        if self.kind == "oauth2":
            if self.oauth2 is None:
                raise ValueError("an oauth2 preset must carry an oauth2 config block")
            if self.issuer is not None or self.issuer_template is not None:
                raise ValueError(
                    "issuer / issuer_template are OIDC-only and must be unset on an "
                    "oauth2 preset"
                )
            return self
        raise ValueError(f"no preset config block is defined for kind {self.kind!r}")


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
