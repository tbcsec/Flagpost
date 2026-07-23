"""Site-wide settings singleton (ARCHITECTURE.md §9, site-wide theming).

One row holds the platform-wide theme + branding an administrator sets for the
whole install: the platform name, the default palette (surface colours) and the
accent (action colours). It is **not** tenant-scoped — theming is site-wide, not
per-competition (ADR-0011) — so, like ``User`` and ``Role`` (§13.1), it does not
use ``CompetitionScopedMixin``.

There is only ever one row. Rather than seed it in a migration, the settings
router lazily creates it with defaults on first read (``get_or_create``), which
keeps tests and fresh installs identical without a data migration. ``id`` is a
fixed sentinel so a second row can't be created by accident.
"""

from datetime import datetime

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin, UtcDateTime, utcnow

# The single row's fixed primary key — the singleton sentinel.
SITE_SETTINGS_ID = "site"

# Shipped defaults for a fresh install: the brand-green ("signal") accent and
# the default dark palette. The frontend theme registry is the source of visual
# truth for what these ids resolve to; the backend only stores + validates them.
DEFAULT_PLATFORM_NAME = "Flagpost"
DEFAULT_PALETTE = "harbor"
DEFAULT_ACCENT = "signal"


class SiteSettings(Base, TimestampMixin):
    __tablename__ = "site_settings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=SITE_SETTINGS_ID)
    platform_name: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_PLATFORM_NAME
    )
    # Palette id (surface colours) — a slug matching a frontend palette preset.
    default_palette: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_PALETTE
    )
    # Accent (action colours) — either a preset slug or a "#RRGGBB" custom hex.
    accent: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ACCENT
    )
    # --- Operational settings (Admin → Site settings) ---
    # Whether the public self-serve /register endpoint accepts new sign-ups.
    # Off = invite-only (admins mint accounts on Admin → Users).
    registration_open: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    # Outbound SMTP for the send_email automation action (§5.3). When smtp_host
    # is set these override the env config; unset = fall back to env (or, if that
    # too is unset, email is a logged no-op). smtp_password is write-only in the
    # API (never serialized back).
    smtp_host: Mapped[str | None] = mapped_column(String, nullable=True)
    smtp_port: Mapped[int] = mapped_column(
        Integer, nullable=False, default=587, server_default="587"
    )
    smtp_username: Mapped[str | None] = mapped_column(String, nullable=True)
    smtp_password: Mapped[str | None] = mapped_column(String, nullable=True)
    smtp_from: Mapped[str] = mapped_column(
        String, nullable=False, default="flagpost@localhost",
        server_default="flagpost@localhost",
    )
    smtp_starttls: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, onupdate=utcnow, nullable=True
    )
