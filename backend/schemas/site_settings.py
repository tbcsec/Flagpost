"""Pydantic schemas for site-wide settings (ARCHITECTURE.md §9).

``default_palette`` and ``accent`` are format-validated, not checked against a
fixed enum here: the frontend theme registry owns the actual list of palettes
and accent presets, and keeping a second copy in sync backend-side would just
drift. Format validation is still strict enough to be the real guard — both
values end up as an HTML attribute value / CSS variable value, so the regexes
below (a slug, or a ``#RRGGBB`` hex for a custom accent) block attribute/CSS
injection regardless of what the frontend offers.
"""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# A palette id is a lowercase slug (matches `data-palette="<id>"`).
PALETTE_PATTERN = r"^[a-z][a-z0-9-]{1,31}$"
# An accent is either a preset slug or a #RRGGBB custom hex.
ACCENT_PATTERN = r"^([a-z][a-z0-9-]{1,31}|#[0-9a-fA-F]{6})$"
# A background style is a slug (matches a frontend renderer id). Same philosophy
# as palette/accent: the frontend owns the actual set and renders "none" for
# anything it doesn't know, so the guard here is only against injection.
BACKGROUND_PATTERN = r"^[a-z][a-z0-9-]{1,31}$"

# A bare domain: labels of 1-63 chars (no leading/trailing hyphen), at least one
# dot. Deliberately rejects "@", a "://" scheme, and a "*." wildcard so a
# malformed entry is caught at save time rather than silently never matching.
_DOMAIN_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
DOMAIN_PATTERN = re.compile(rf"^{_DOMAIN_LABEL}(\.{_DOMAIN_LABEL})+$")
MAX_ALLOWED_DOMAINS = 50
MAX_DOMAIN_LENGTH = 253


def _validate_domain(raw: str) -> str:
    domain = raw.strip().lower()
    if not domain or len(domain) > MAX_DOMAIN_LENGTH or not DOMAIN_PATTERN.match(domain):
        raise ValueError(f"Not a valid domain: {raw!r}")
    return domain


class SiteSettingsOut(BaseModel):
    """Public shape — served unauthenticated so the login/register screens can
    brand themselves before there's a session, and know whether to offer sign-up."""

    model_config = ConfigDict(from_attributes=True)

    platform_name: str
    default_palette: str
    accent: str
    # Front-door animated background slug (#195); "none" = flat. Public so the
    # login/register/public pages can render it before there's a session.
    background_style: str = "none"
    registration_open: bool
    # Public path to the custom org logo (with a cache-busting version), or None
    # when the built-in Flagpost mark should be used. Needed pre-auth so the
    # login/register lockup can render the org's brand.
    logo_url: str | None
    # Whether the platform-name wordmark shows beside the logo in the lockup.
    show_wordmark: bool
    # Whether this instance is running in demo mode (config-driven, not stored) —
    # drives the "resets hourly" banner and the login-page demo credentials. The
    # router sets it from settings.demo_mode; defaults false everywhere else.
    demo_mode: bool = False
    # Archived-competition retention policy (#26). Public because the archive
    # confirm dialog (edit_competition holders, who may lack manage_site_settings)
    # must show the exact deletion date before the admin commits. Benign to
    # disclose — a retention window, not infrastructure detail.
    archive_auto_delete: bool = True
    archive_retention_days: int = 30
    # Whether public registration currently requires an email (the domain
    # allowlist is enabled, or email verification is enabled — either makes an
    # address mandatory). The allowlist/verification internals stay admin-only —
    # only this policy bit, which the register page needs to mark the field
    # required.
    email_required: bool = False
    # Whether an unverified account is blocked from joining a competition
    # (issue #74). Public so the join button / profile banner can explain a
    # 403 without a round-trip to admin-only settings.
    email_verification_enabled: bool = False


class SiteSettingsUpdate(BaseModel):
    platform_name: str = Field(min_length=1, max_length=64)
    default_palette: str = Field(pattern=PALETTE_PATTERN)
    accent: str = Field(pattern=ACCENT_PATTERN)
    # **Omitted / null = leave unchanged** — the update_checks_enabled
    # precedent, not `= "none"`. This PUT replaces the whole object, so a
    # defaulted value would let a scripted client that changes the platform
    # name and omits this field silently clear a configured background. An
    # explicit "none" resets it; the Appearance form always sends it.
    background_style: str | None = Field(default=None, pattern=BACKGROUND_PATTERN)
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
    archive_auto_delete: bool
    archive_retention_days: int
    # Email-domain allowlist for public registration (#56). Admin-only surface —
    # the domain list itself is never exposed on the public SiteSettingsOut.
    email_domain_allowlist_enabled: bool
    allowed_email_domains: list[str]
    # Email verification gate (#74): requires SMTP to be configured (checked at
    # the write layer — see routers.site_settings.update_operational_settings).
    email_verification_enabled: bool
    # Update check + adoption count (#111). The timestamp sits beside the toggle
    # in the admin UI so an operator can see whether the check is actually
    # working, rather than inferring it from the absence of a notice.
    update_checks_enabled: bool
    last_update_check_at: datetime | None = None
    last_update_check_status: str | None = None
    # What this deployment is running, and the newest the endpoint has reported.
    current_version: str = "dev"
    latest_known_version: str | None = None
    # Raw fact: a newer release exists. Deliberately *not* dismissal-adjusted —
    # the settings page must report the truth even after the banner is waved
    # away. The banner combines the two.
    update_available: bool = False
    update_notice_dismissed: bool = False
    updated_at: datetime | None


class BackupExportRequest(BaseModel):
    """Which sections to include in an export (a subset of ``backup.SECTIONS``)."""

    sections: list[str] = Field(default_factory=list)


class BackupImportRequest(BaseModel):
    """A previously-exported document plus the sections to import from it."""

    sections: list[str] = Field(default_factory=list)
    # The parsed export JSON — opaque here; validated by the backup engine.
    payload: dict = Field(default_factory=dict)


class OperationalSettingsUpdate(BaseModel):
    registration_open: bool
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_from: str = Field(default="flagpost@localhost", min_length=1, max_length=320)
    smtp_starttls: bool = True
    # Omitted / null = leave the stored password unchanged; a value replaces it.
    smtp_password: str | None = Field(default=None, max_length=255)
    # Archived-competition retention (#26): 1 day to 10 years.
    archive_auto_delete: bool = True
    archive_retention_days: int = Field(default=30, ge=1, le=3650)
    # Email-domain allowlist for public registration (#56). Domains are
    # normalized (lowercased, deduped) and format-validated; a malformed entry
    # rejects the whole save (422) rather than being silently dropped.
    email_domain_allowlist_enabled: bool = False
    allowed_email_domains: list[str] = Field(default_factory=list)
    # Email verification gate (#74). Turning this on 400s at the router layer
    # unless SMTP is configured (this write's smtp_host, or the env fallback) —
    # there'd be no way to deliver the confirmation link otherwise.
    email_verification_enabled: bool = False
    # Update check + adoption count (#111). **Omitted / null = leave unchanged**,
    # like smtp_password above — not `= True`. This PUT replaces the whole
    # object, so a default would let a scripted client that changes SMTP and
    # omits this field silently opt the install back in. Re-enabling a
    # privacy-relevant setting by omission is exactly the surprise to avoid.
    update_checks_enabled: bool | None = None

    @field_validator("allowed_email_domains")
    @classmethod
    def _validate_allowed_email_domains(cls, domains: list[str]) -> list[str]:
        if len(domains) > MAX_ALLOWED_DOMAINS:
            raise ValueError(f"At most {MAX_ALLOWED_DOMAINS} domains are allowed")
        deduped: list[str] = []
        for raw in domains:
            domain = _validate_domain(raw)
            if domain not in deduped:
                deduped.append(domain)
        return deduped
