"""Schemas for the public OIDC login surface (#58).

Admin CRUD schemas live in ``schemas/auth_providers`` (ADR-0022) — this module
keeps only what the unauthenticated login page and /profile may see."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExternalIdentityOut(BaseModel):
    """A link shown on /profile so a user can see how they sign in."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_name: str
    provider_slug: str
    email: str | None
    created_at: datetime
