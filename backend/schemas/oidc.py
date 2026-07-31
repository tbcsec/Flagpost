"""Schemas for OIDC provider config and the public login surface (#58)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OidcProviderPublic(BaseModel):
    """What an unauthenticated login page may know: enough to draw a button.

    Deliberately excludes the issuer and client_id — a login page has no use for
    them, and not publishing an install's IdP topology is free.
    """

    slug: str
    name: str


class OidcProviderOut(BaseModel):
    """Admin view. The client secret is **write-only**: only whether one is set
    is ever returned, matching the SMTP-password precedent."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    issuer: str
    client_id: str
    scopes: str
    enabled: bool
    created_at: datetime
    client_secret_set: bool = False
    # The exact value to register at the IdP. Computed server-side because it
    # depends on PUBLIC_BASE_URL, which the browser can't know — and a mismatch
    # here is the single most common reason an OIDC setup fails.
    redirect_uri: str = ""


class OidcProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # Lowercase URL-safe; validated in the router against a stricter pattern.
    slug: str = Field(min_length=1, max_length=60)
    issuer: str = Field(min_length=1, max_length=500)
    client_id: str = Field(min_length=1, max_length=500)
    client_secret: str | None = Field(default=None, max_length=1000)
    scopes: str = Field(default="openid email profile", max_length=500)
    enabled: bool = False


class OidcProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    issuer: str | None = Field(default=None, min_length=1, max_length=500)
    client_id: str | None = Field(default=None, min_length=1, max_length=500)
    # None leaves the stored secret untouched; "" clears it (public client).
    client_secret: str | None = Field(default=None, max_length=1000)
    scopes: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None


class ExternalIdentityOut(BaseModel):
    """A link shown on /profile so a user can see how they sign in."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_name: str
    provider_slug: str
    email: str | None
    created_at: datetime
