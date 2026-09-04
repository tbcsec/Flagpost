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
from utils.crypto import EncryptedString

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
    # When first-run provisioning completed (ADR-0017). One-way: nothing clears
    # it, and the setup wizard refuses to run once it is set. Losing every active
    # Administrator is an operator problem; it must never reopen a public
    # endpoint that mints one on a live install.
    setup_completed_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
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
    # Front-door animated background (#195) — a slug the frontend maps to a
    # canvas renderer ("none" | "aurora" | "gradient" | "constellation"). Only
    # shown on the out-of-shell pages (login/register/setup/public) and only on
    # dark palettes; "none" (the default) is today's flat ground. A third
    # theming axis alongside palette + accent (ADR-0011, site-wide).
    background_style: Mapped[str] = mapped_column(
        String, nullable=False, default="none", server_default="none"
    )
    # Custom sign-in notice (#197): a rich-text (ProseMirror JSON) document
    # rendered above the sign-in card on /login. Null = no notice. The same
    # opaque shape as ``rules_text`` — stored, never interpreted server-side;
    # the read-only TipTap view renders it as a React tree (no raw HTML path).
    login_notice: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Demo login accounts (#360): a list of {label, description, identifier,
    # password} the login page renders as click-to-sign-in buttons on a demo
    # instance. Data-driven so a custom baseline (#357) can carry its OWN demo
    # accounts instead of the hardcoded stock seed. Passwords are plaintext by
    # necessity (the card fills them) and reference public throwaway accounts —
    # only ever exposed/rendered when demo_mode is on (see routers/site_settings
    # and the login card). Stored regardless of mode so it rides the backup.
    demo_credentials: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
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
    # Whether accounts may rename themselves from the profile page (#298). Off
    # pins usernames to what was provisioned — only the self-service path is
    # gated; manage_users holders can always rename from Admin → Users.
    username_changes_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    # Site-wide switch for the cross-competition skills web (#364, ADR-0039). On
    # by default. Off makes both skills reads 404 (the router guard) and hides the
    # UI. It's a *site* flag, not a per-competition module toggle, because the web
    # spans every competition — hence a SiteSettings column, not competition_modules.
    skills_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    # Outbound SMTP for the send_email automation action (§5.3). When smtp_host
    # is set these override the env config; unset = fall back to env (or, if that
    # too is unset, email is a logged no-op).
    smtp_host: Mapped[str | None] = mapped_column(String, nullable=True)
    smtp_port: Mapped[int] = mapped_column(
        Integer, nullable=False, default=587, server_default="587"
    )
    smtp_username: Mapped[str | None] = mapped_column(String, nullable=True)
    # The password must be *presented* to the mail server, so it's encrypted at
    # rest, not hashed (ADR-0020) — the same treatment as the OIDC client secret.
    # The underlying column is still TEXT (EncryptedString.impl = String), so
    # adopting the type needs no schema change; the 2026-08-02 migration encrypts
    # the one pre-existing plaintext value. Write-only in the API (never
    # serialized back — GET exposes only `smtp_password_set`), and dropped from
    # the backup export (utils/backup — a per-install key makes it useless off-box).
    #
    # **Deferred**, like the logo blob above, and for a sharper reason than size:
    # decryption runs when the column loads, and it *raises* on a key mismatch
    # (crypto.EncryptedString). This row is read on the public pre-auth path for
    # branding and on the admin settings page — the very page an operator needs
    # to re-enter the secret after a lost/rotated key. Eager-decrypting here would
    # 500 all of those the moment the key changed, blocking the documented
    # recovery. Deferring keeps ordinary loads clear of the secret; the mailer,
    # the sole point of use, undefers it explicitly, so a key failure surfaces at
    # the SMTP send that actually needs it — which is what ADR-0020 wants.
    smtp_password: Mapped[str | None] = mapped_column(
        EncryptedString, nullable=True, deferred=True
    )
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
    # Update check + anonymous adoption count (#111). One daily request to
    # `update_check_url` sending only this deployment's version; the response
    # drives the admin update notice, and the request itself — counted, never
    # logged — is the project's adoption signal. On by default; this is the
    # operator's off switch (there's also an env var, so an air-gapped install
    # need never make the call at all).
    update_checks_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    # Last *successful* check. Drives the 24h cadence, and is shown beside the
    # toggle so an admin can see the feature is alive (or isn't).
    last_update_check_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    # Last attempt, successful or not. Separate from the above so a failing
    # endpoint backs off hourly instead of retrying on every scheduler tick.
    last_update_attempt_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    # "ok" | "unreachable" | "error" — shown to admins, never to competitors.
    last_update_check_status: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    # Newest version the endpoint reported, compared against the running version
    # to decide whether to show the notice.
    latest_known_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # The version an admin dismissed the notice for. The notice returns only once
    # something newer than this ships, so a given release nags at most once.
    dismissed_update_version: Mapped[str | None] = mapped_column(
        String, nullable=True
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
