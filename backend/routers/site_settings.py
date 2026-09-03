"""Site-wide settings routes (ARCHITECTURE.md §9, site-wide theming).

- ``GET  /api/site-settings`` is **public** (no auth): the login/register
  screens need the platform name + theme before there's a session.
- ``PUT  /api/site-settings`` is gated on the new global ``manage_site_settings``
  permission (§7.1, Administrator-only). It's a mutation, so it emits
  ``site.settings_updated`` (§3.2) — the audit log picks it up like any event.

The single settings row is created lazily with defaults on first read
(``get_or_create``) so a fresh install and the test DB behave identically
without a data migration.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy import String, select, type_coerce
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from auth.deps import require_permission, user_has_permission
from config import settings as app_config
from db import get_db, utcnow
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.theme_preset import ThemePreset
from models.user import User
from schemas.rules import RulesSettingsOut, RulesSettingsUpdate
from schemas.site_settings import (
    BackupExportRequest,
    BackupImportRequest,
    OperationalSettingsOut,
    OperationalSettingsUpdate,
    SiteSettingsAdminOut,
    SiteSettingsOut,
    SiteSettingsUpdate,
)
from storage import get_storage
from storage.base import ObjectStorage
from utils import backup, mailer
from utils.event_bus import event_bus
from utils.image_sniff import exceeds_pixel_budget, sniff_logo_type
from utils.update_check import notice_dismissed, update_available
from utils.uploads import read_upload_capped

router = APIRouter(prefix="/api/site-settings", tags=["site-settings"])

# A custom logo is small by nature; cap it well under an attachment. Big enough
# for a detailed SVG or a 2x raster mark, small enough to sit in the DB row.
MAX_LOGO_BYTES = 1 * 1024 * 1024  # 1 MB


async def get_or_create_settings(db: AsyncSession) -> SiteSettings:
    settings = await db.get(SiteSettings, SITE_SETTINGS_ID)
    if settings is None:
        settings = SiteSettings(id=SITE_SETTINGS_ID)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


async def _resolve_active_theme(db: AsyncSession, settings: SiteSettings) -> None:
    """Annotate the row with the active custom theme's token pack (#323) when
    ``default_palette`` names a preset, so it's carried by EVERY response that
    feeds the site-settings cache (read *and* the write/logo routes) — the
    ThemeApplier reads it from that cache, so a save that dropped it would revert
    the whole site to the default palette. ``db.get`` returns None for a built-in
    id or an unknown one."""
    settings.active_theme = await db.get(ThemePreset, settings.default_palette)


@router.get("", response_model=SiteSettingsOut)
async def read_site_settings(db: AsyncSession = Depends(get_db)) -> SiteSettingsOut:
    # Public: the branding is needed before authentication.
    settings = await get_or_create_settings(db)
    await _resolve_active_theme(db, settings)
    out = SiteSettingsOut.model_validate(settings)
    # demo_mode is config-driven, not stored.
    out.demo_mode = app_config.demo_mode
    # email_required mirrors the allowlist + verification flags; the domain
    # list itself stays admin-only (see OperationalSettingsOut).
    out.email_required = (
        settings.email_domain_allowlist_enabled or settings.email_verification_enabled
    )
    # Demo login accounts (#360) only ever leave the server on a demo instance —
    # a production login page never exposes them. Blanked on the response, not on
    # the ORM column (which stays intact and rides the backup).
    if not app_config.demo_mode:
        out.demo_credentials = []
    return out


@router.put("", response_model=SiteSettingsAdminOut)
async def update_site_settings(
    body: SiteSettingsUpdate,
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> SiteSettingsAdminOut:
    settings = await get_or_create_settings(db)
    settings.platform_name = body.platform_name
    settings.default_palette = body.default_palette
    settings.accent = body.accent
    # Omitted / null = leave unchanged (see SiteSettingsUpdate) — only an
    # explicit value (including "none") writes.
    if body.background_style is not None:
        settings.background_style = body.background_style
    # For the notice null is meaningful (= clear it), so omitted and null must
    # be told apart: only a field the client actually sent writes (#197).
    if "login_notice" in body.model_fields_set:
        settings.login_notice = body.login_notice
    settings.show_wordmark = body.show_wordmark
    # Demo login accounts (#360). Omitted / null = leave unchanged; an explicit
    # list (including []) writes. Stored regardless of demo_mode — only exposed
    # when demo_mode (public GET) — so a baseline authored anywhere carries them.
    if body.demo_credentials is not None:
        settings.demo_credentials = [c.model_dump() for c in body.demo_credentials]
    await db.commit()
    await db.refresh(settings)
    # Carry the active theme on the admin response so the cache the ThemeApplier
    # reads keeps it after a save (#323).
    await _resolve_active_theme(db, settings)
    # The admin cache is keyed the same as the public read, so carry the
    # config-driven demo_mode / email_required on the response too — otherwise a
    # save would clobber them to false in the cache and hide the demo editor
    # (and banner) until refetch.
    admin_out = SiteSettingsAdminOut.model_validate(settings)
    admin_out.demo_mode = app_config.demo_mode
    admin_out.email_required = (
        settings.email_domain_allowlist_enabled or settings.email_verification_enabled
    )

    await event_bus.emit(
        "site.settings_updated",
        {
            "user_id": current_user.id,
            "platform_name": settings.platform_name,
            "default_palette": settings.default_palette,
            "accent": settings.accent,
            "background_style": settings.background_style,
            # The doc itself stays out of the event — audit rows shouldn't
            # carry page-sized payloads; set/cleared is the auditable fact.
            "login_notice_set": settings.login_notice is not None,
        },
    )
    return admin_out


@router.post("/logo", response_model=SiteSettingsAdminOut)
async def upload_logo(
    file: UploadFile,
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> SiteSettings:
    """Store a custom org logo that replaces the built-in mark in the lockup.
    Kept in the DB (not object storage) so branding works on the infra-free
    stack and pre-auth. Emits ``site.settings_updated`` like any branding change."""
    data = await read_upload_capped(file, MAX_LOGO_BYTES)
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file"
        )

    # Derive the type from the bytes, never the client's Content-Type (#114): a
    # renamed non-image with a spoofed header must be rejected, and what we store
    # + serve back has to be what the file actually is for the nosniff header on
    # the download path to mean anything. The sniff result is the allowlist.
    content_type = sniff_logo_type(data)
    if content_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Logo must be a PNG, JPEG, WebP, GIF, or SVG image",
        )
    # Same decode-bomb guard the ticket-attachment path uses: a byte cap doesn't
    # bound the cost of rendering a huge-dimensioned raster in the browser.
    if exceeds_pixel_budget(data, content_type):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Logo image dimensions are too large",
        )

    settings = await get_or_create_settings(db)
    settings.logo_data = data
    settings.logo_content_type = content_type
    settings.logo_updated_at = utcnow()
    await db.commit()
    await db.refresh(settings)
    await _resolve_active_theme(db, settings)  # keep the active theme in the cache (#323)

    await event_bus.emit(
        "site.settings_updated",
        {"user_id": current_user.id, "section": "logo"},
    )
    return settings


@router.delete("/logo", response_model=SiteSettingsAdminOut)
async def delete_logo(
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> SiteSettings:
    """Clear the custom logo, reverting the lockup to the built-in Flagpost mark."""
    settings = await get_or_create_settings(db)
    settings.logo_data = None
    settings.logo_content_type = None
    settings.logo_updated_at = None
    await db.commit()
    await db.refresh(settings)
    await _resolve_active_theme(db, settings)  # keep the active theme in the cache (#323)

    await event_bus.emit(
        "site.settings_updated",
        {"user_id": current_user.id, "section": "logo"},
    )
    return settings


# --- Platform export / import (Admin → Site settings, ADR-0016) --------------
# Full-fidelity, section-selectable backup. Gated on manage_site_settings — the
# Administrator-only permission this page already uses; the export carries whole-
# platform data (users, flag hashes), so it must stay tightly held.


@router.get("/backup/sections", response_model=list[str])
async def backup_sections(
    _user: User = Depends(require_permission("manage_site_settings")),
) -> list[str]:
    """The selectable export/import sections, in display order."""
    return list(backup.SECTIONS)


async def _require_section_permissions(
    db: AsyncSession, user: User, sections: list[str]
) -> None:
    """The roles and users sections carry the RBAC graph and account rows, so
    reading or writing them requires the dedicated global grants — not just
    manage_site_settings. Without this gate, a site-settings delegate could
    import a global Administrator role assignment and self-escalate (the import
    path has no equivalent of the role editor's grant containment)."""
    if "roles" in sections and not await user_has_permission(
        db, user.id, "manage_roles", None
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The roles section requires the Manage roles permission",
        )
    if "users" in sections and not await user_has_permission(
        db, user.id, "manage_users", None
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The users section requires the Manage users permission",
        )


@router.post("/export")
async def export_backup(
    body: BackupExportRequest,
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    if not body.sections:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one section to export",
        )
    await _require_section_permissions(db, current_user, body.sections)
    document = await backup.export_data(db, storage, body.sections)
    import json

    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    return Response(
        content=json.dumps(document, separators=(",", ":")),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="flagpost-export-{stamp}.json"'
        },
    )


@router.post("/import")
async def import_backup(
    body: BackupImportRequest,
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> dict[str, dict[str, int]]:
    if not body.sections:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one section to import",
        )
    await _require_section_permissions(db, current_user, body.sections)
    try:
        result = await backup.import_data(
            db, storage, body.payload, body.sections, actor=current_user
        )
    except backup.ImportForbidden as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except backup.ImportError_ as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    total = sum(counts["created"] for counts in result.values())
    await event_bus.emit(
        "platform.imported",
        {
            "user_id": current_user.id,
            "sections": body.sections,
            "created": total,
        },
    )
    return result


@router.get("/logo")
async def read_logo(db: AsyncSession = Depends(get_db)) -> Response:
    """Stream the custom logo bytes. **Public** — the login/register lockup needs
    it before auth. The blob is ``deferred`` on the model, so undefer it here; the
    settings row's normal reads still skip it. Served defensively so a
    direct-navigation SVG can't execute script (it's rendered via ``<img>`` in the
    app, which already neuters SVG scripting, but a pasted URL would not)."""
    settings = await db.scalar(
        select(SiteSettings)
        .where(SiteSettings.id == SITE_SETTINGS_ID)
        .options(undefer(SiteSettings.logo_data))
    )
    if settings is None or settings.logo_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No logo set"
        )
    return Response(
        content=settings.logo_data,
        media_type=settings.logo_content_type or "application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            # Neutralise any script/network in a directly-opened SVG logo.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        },
    )


# --- Rules / code of conduct (issue #57) --------------------------------------
# The site-wide rules document users must accept before joining a competition
# (unless a per-competition override supersedes it, or display-only is on).
# Follows the /operational sub-resource precedent: manage_site_settings-gated
# GET/PUT, emitting site.settings_updated with a section marker. Editing the
# global text does NOT reset acceptances (owner decision, v1) — only a
# per-competition override change does (see update_competition).


@router.get("/rules", response_model=RulesSettingsOut)
async def read_rules_settings(
    _user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> RulesSettingsOut:
    settings = await get_or_create_settings(db)
    return RulesSettingsOut(
        rules_text=settings.rules_text,
        rules_display_only=settings.rules_display_only,
    )


@router.put("/rules", response_model=RulesSettingsOut)
async def update_rules_settings(
    body: RulesSettingsUpdate,
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> RulesSettingsOut:
    settings = await get_or_create_settings(db)
    settings.rules_text = body.rules_text
    settings.rules_display_only = body.rules_display_only
    await db.commit()
    await db.refresh(settings)

    await event_bus.emit(
        "site.settings_updated",
        {"user_id": current_user.id, "section": "rules"},
    )
    return RulesSettingsOut(
        rules_text=settings.rules_text,
        rules_display_only=settings.rules_display_only,
    )


async def _smtp_password_present(db: AsyncSession) -> bool:
    """Whether an SMTP password is stored — without decrypting it.

    `smtp_password` is a deferred `EncryptedString`; reading the attribute would
    load and decrypt it, which raises on a key mismatch (the exact state the
    settings page must stay usable through). `type_coerce` to plain `String`
    reads the raw ciphertext straight past the decrypt, so presence is knowable
    even when the key is wrong. `smtp_password_set` never needed the plaintext.
    """
    raw = await db.scalar(
        select(type_coerce(SiteSettings.__table__.c.smtp_password, String)).where(
            SiteSettings.__table__.c.id == SITE_SETTINGS_ID
        )
    )
    return bool(raw)


def _operational_out(
    settings: SiteSettings, *, smtp_password_set: bool
) -> OperationalSettingsOut:
    return OperationalSettingsOut(
        registration_open=settings.registration_open,
        username_changes_enabled=settings.username_changes_enabled,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_username=settings.smtp_username,
        smtp_from=settings.smtp_from,
        smtp_starttls=settings.smtp_starttls,
        smtp_password_set=smtp_password_set,
        archive_auto_delete=settings.archive_auto_delete,
        archive_retention_days=settings.archive_retention_days,
        email_domain_allowlist_enabled=settings.email_domain_allowlist_enabled,
        allowed_email_domains=settings.allowed_email_domains or [],
        update_checks_enabled=settings.update_checks_enabled,
        last_update_check_at=settings.last_update_check_at,
        last_update_check_status=settings.last_update_check_status,
        current_version=app_config.app_version,
        latest_known_version=settings.latest_known_version,
        update_available=update_available(settings),
        update_notice_dismissed=notice_dismissed(settings),
        email_verification_enabled=settings.email_verification_enabled,
        updated_at=settings.updated_at,
    )


@router.get("/operational", response_model=OperationalSettingsOut)
async def read_operational_settings(
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> OperationalSettingsOut:
    """Registration policy + SMTP config — admin-only (never public; carries the
    mail server address). The SMTP password is not returned (§`smtp_password_set`)."""
    return _operational_out(
        await get_or_create_settings(db),
        smtp_password_set=await _smtp_password_present(db),
    )


@router.put("/operational", response_model=OperationalSettingsOut)
async def update_operational_settings(
    body: OperationalSettingsUpdate,
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> OperationalSettingsOut:
    # Email verification (#74) needs somewhere to deliver the confirmation
    # link — refuse to turn it on without SMTP (this write's host, or the env
    # fallback), rather than silently no-op every send.
    if body.email_verification_enabled and not mailer.is_configured(body.smtp_host):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Configure SMTP before enabling email verification",
        )
    settings = await get_or_create_settings(db)
    settings.registration_open = body.registration_open
    # Omitted = unchanged (#298), the update_checks_enabled pattern below.
    if body.username_changes_enabled is not None:
        settings.username_changes_enabled = body.username_changes_enabled
    settings.smtp_host = body.smtp_host or None
    settings.smtp_port = body.smtp_port
    settings.smtp_username = body.smtp_username or None
    settings.smtp_from = body.smtp_from
    settings.smtp_starttls = body.smtp_starttls
    # Write-only password: only replace it when a new value is supplied.
    if body.smtp_password is not None:
        settings.smtp_password = body.smtp_password or None
    # Retention policy (#26). Changing it never touches already-stamped
    # purge_after clocks — it only governs future archive actions.
    settings.archive_auto_delete = body.archive_auto_delete
    settings.archive_retention_days = body.archive_retention_days
    settings.email_domain_allowlist_enabled = body.email_domain_allowlist_enabled
    settings.allowed_email_domains = body.allowed_email_domains
    settings.email_verification_enabled = body.email_verification_enabled
    if body.update_checks_enabled is not None:
        settings.update_checks_enabled = body.update_checks_enabled
    await db.commit()
    await db.refresh(settings)

    await event_bus.emit(
        "site.settings_updated",
        {"user_id": current_user.id, "section": "operational"},
    )
    return _operational_out(
        settings, smtp_password_set=await _smtp_password_present(db)
    )


@router.post("/update-notice/dismiss", response_model=OperationalSettingsOut)
async def dismiss_update_notice(
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> OperationalSettingsOut:
    """Hide the update notice until something newer than the current latest ships.

    Records the *version* dismissed rather than a timestamp or a boolean: a
    timestamp would need a re-show policy to tune, and a boolean would swallow
    the next release. Pinning it to a version means a given release nags at most
    once, and a genuinely newer one always gets through (#111).

    Not a settings mutation in the meaningful sense — no event, since a personal
    "I've seen this" isn't something an audit reader needs.
    """
    settings = await get_or_create_settings(db)
    settings.dismissed_update_version = settings.latest_known_version
    await db.commit()
    await db.refresh(settings)
    return _operational_out(
        settings, smtp_password_set=await _smtp_password_present(db)
    )
