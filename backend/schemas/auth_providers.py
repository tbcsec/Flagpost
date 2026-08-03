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

from pydantic import BaseModel, ConfigDict, Field, ValidationError


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


# kind -> config model. SAML (#100) and LDAP (#101) register theirs alongside
# their transports.
PROVIDER_CONFIG_MODELS: dict[str, type[BaseModel]] = {"oidc": OidcConfig}


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
