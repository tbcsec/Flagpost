"""Pydantic schemas for site-wide settings (ARCHITECTURE.md §9).

``default_palette`` and ``accent`` are format-validated, not checked against a
fixed enum here: the frontend theme registry owns the actual list of palettes
and accent presets, and keeping a second copy in sync backend-side would just
drift. Format validation is still strict enough to be the real guard — both
values end up as an HTML attribute value / CSS variable value, so the regexes
below (a slug, or a ``#RRGGBB`` hex for a custom accent) block attribute/CSS
injection regardless of what the frontend offers.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# A palette id is a lowercase slug (matches `data-palette="<id>"`).
PALETTE_PATTERN = r"^[a-z][a-z0-9-]{1,31}$"
# An accent is either a preset slug or a #RRGGBB custom hex.
ACCENT_PATTERN = r"^([a-z][a-z0-9-]{1,31}|#[0-9a-fA-F]{6})$"


class SiteSettingsOut(BaseModel):
    """Public shape — served unauthenticated so the login/register screens can
    brand themselves before there's a session, and know whether to offer sign-up."""

    model_config = ConfigDict(from_attributes=True)

    platform_name: str
    default_palette: str
    accent: str
    registration_open: bool
    # Public path to the custom org logo (with a cache-busting version), or None
    # when the built-in Flagpost mark should be used. Needed pre-auth so the
    # login/register lockup can render the org's brand.
    logo_url: str | None
    # Whether the platform-name wordmark shows beside the logo in the lockup.
    show_wordmark: bool


class SiteSettingsUpdate(BaseModel):
    platform_name: str = Field(min_length=1, max_length=64)
    default_palette: str = Field(pattern=PALETTE_PATTERN)
    accent: str = Field(pattern=ACCENT_PATTERN)
    show_wordmark: bool = True


class SiteSettingsAdminOut(SiteSettingsOut):
    """Admin shape — adds the last-updated timestamp for the settings page."""

    updated_at: datetime | None


class OperationalSettingsOut(BaseModel):
    """The operational (non-theming) site config — registration policy + SMTP.
    The SMTP password is never serialized back; ``smtp_password_set`` says whether
    one is stored."""

    model_config = ConfigDict(from_attributes=True)

    registration_open: bool
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_from: str
    smtp_starttls: bool
    smtp_password_set: bool
    updated_at: datetime | None


class OperationalSettingsUpdate(BaseModel):
    registration_open: bool
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_from: str = Field(default="flagpost@localhost", min_length=1, max_length=320)
    smtp_starttls: bool = True
    # Omitted / null = leave the stored password unchanged; a value replaces it.
    smtp_password: str | None = Field(default=None, max_length=255)
