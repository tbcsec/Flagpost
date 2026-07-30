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

from sqlalchemy import JSON, Boolean, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin, UtcDateTime, ensure_aware_utc, utcnow

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
    # --- Branding (Admin → Site settings → Appearance) ---
    # A custom organisation logo that replaces the built-in Flagpost mark in the
    # lockup (sidebar / login / register). Stored as a blob **in the DB**, not in
    # object storage, so branding works on the infra-free stack and pre-auth
    # (like the collab snapshot, ADR-0014). The bytes are ``deferred`` so the
    # frequently-read settings row never drags the image along — only the public
    # ``GET .../logo`` streaming endpoint undefers it. ``logo_content_type`` being
    # set is the "a logo exists" flag (checkable without loading the blob).
    logo_data: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True, deferred=True
    )
    logo_content_type: Mapped[str | None] = mapped_column(String, nullable=True)
    logo_updated_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    # Whether the platform-name wordmark shows beside the logo. Orgs whose logo
    # already bakes in their name turn this off; icon-only marks keep it on.
    # Flagpost stays attributed regardless via the mandatory "Powered by" footer.
    show_wordmark: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
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
    # Archived-competition retention (#26): when on, archiving a competition
    # stamps it `purge_after = now + archive_retention_days`, and the scheduler
    # hard-deletes it (DB tree + attachment objects) once that passes. Only
    # competitions archived *while this is on* ever get a clock — pre-existing
    # archives keep purge_after = NULL and are never auto-deleted.
    archive_auto_delete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    archive_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
    # Email-domain allowlist for public self-serve registration only (#56). When
    # on, POST /register requires an email whose domain (or a subdomain of one)
    # appears in allowed_email_domains; admin-created accounts and later email
    # edits are unaffected. A null/empty list with the flag on locks registration
    # to nobody — that's the admin's call, not validated away here.
    email_domain_allowlist_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    allowed_email_domains: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Email verification gate (issue #74): when on, a self-registered account
    # must confirm its email (mailed link) before it can join a competition.
    # Enabling it requires SMTP to already be configured (checked at the
    # settings-write layer, not here). Admin-created accounts are exempt.
    email_verification_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Site-wide rules / code of conduct (issue #57): a rich-text (ProseMirror
    # JSON) document shown to users before they join any competition. Null = no
    # rules configured, no gate anywhere. A competition's ``rules_override``
    # supersedes this for that competition.
    rules_text: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # When true the rules are informational only — shown at join, but no forced
    # "I accept" and no join gate. Travels with this (global) document; an
    # override carries its own flag on the competition row.
    rules_display_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, onupdate=utcnow, nullable=True
    )

    @property
    def logo_url(self) -> str | None:
        """Stable public path to the custom logo, or ``None`` if unset. Carries a
        ``?v=`` version (the logo's last-updated epoch) so a replaced logo busts
        any client/CDN cache. Reads only non-deferred columns, so exposing it on
        the settings row doesn't load the blob."""
        if not self.logo_content_type:
            return None
        version = (
            int(ensure_aware_utc(self.logo_updated_at).timestamp())
            if self.logo_updated_at
            else 0
        )
        return f"/api/site-settings/logo?v={version}"
