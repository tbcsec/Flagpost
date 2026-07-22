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
    brand themselves before there's a session."""

    model_config = ConfigDict(from_attributes=True)

    platform_name: str
    default_palette: str
    accent: str


class SiteSettingsUpdate(BaseModel):
    platform_name: str = Field(min_length=1, max_length=64)
    default_palette: str = Field(pattern=PALETTE_PATTERN)
    accent: str = Field(pattern=ACCENT_PATTERN)


class SiteSettingsAdminOut(SiteSettingsOut):
    """Admin shape — adds the last-updated timestamp for the settings page."""

    updated_at: datetime | None
