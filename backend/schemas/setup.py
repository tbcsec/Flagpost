"""First-run setup wizard schemas (ADR-0017)."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from schemas.site_settings import ACCENT_PATTERN, PALETTE_PATTERN


class SetupStatusOut(BaseModel):
    needs_setup: bool


class SetupAdmin(BaseModel):
    """The owner account to create — the display name is the login identifier
    (§7.7); email is optional (ADR-0015)."""

    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=256)
    email: EmailStr | None = None


class SetupRequest(BaseModel):
    admin: SetupAdmin
    # Initial branding + one operational setting — nothing competition-scoped. The
    # logo and SMTP are configured later on their dedicated Admin pages.
    platform_name: str = Field(min_length=1, max_length=64)
    default_palette: str = Field(pattern=PALETTE_PATTERN)
    accent: str = Field(pattern=ACCENT_PATTERN)
    registration_open: bool = True
    # Update check + anonymous adoption count (#111). Offered here — rather than
    # only in Admin later — so an operator can decline *before* the first check
    # ever fires, which is the difference between a choice and a notification.
    update_checks_enabled: bool = True
