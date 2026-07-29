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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from auth.deps import require_permission
from config import settings as app_config
from db import get_db, utcnow
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
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

router = APIRouter(prefix="/api/site-settings", tags=["site-settings"])

# A custom logo is small by nature; cap it well under an attachment. Big enough
# for a detailed SVG or a 2x raster mark, small enough to sit in the DB row.
MAX_LOGO_BYTES = 1 * 1024 * 1024  # 1 MB
ALLOWED_LOGO_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/svg+xml",
}


async def get_or_create_settings(db: AsyncSession) -> SiteSettings:
    settings = await db.get(SiteSettings, SITE_SETTINGS_ID)
    if settings is None:
        settings = SiteSettings(id=SITE_SETTINGS_ID)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


@router.get("", response_model=SiteSettingsOut)
async def read_site_settings(db: AsyncSession = Depends(get_db)) -> SiteSettings:
    # Public: the branding is needed before authentication.
    settings = await get_or_create_settings(db)
    # demo_mode is config-driven, not stored — annotate the row for serialization.
    settings.demo_mode = app_config.demo_mode
    # email_required mirrors the allowlist + verification flags; the domain
    # list itself stays admin-only (see OperationalSettingsOut).
    settings.email_required = (
        settings.email_domain_allowlist_enabled or settings.email_verification_enabled
    )
    return settings


@router.put("", response_model=SiteSettingsAdminOut)
async def update_site_settings(
    body: SiteSettingsUpdate,
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> SiteSettings:
    settings = await get_or_create_settings(db)
    settings.platform_name = body.platform_name
    settings.default_palette = body.default_palette
    settings.accent = body.accent
    settings.show_wordmark = body.show_wordmark
    await db.commit()
    await db.refresh(settings)

    await event_bus.emit(
        "site.settings_updated",
        {
            "user_id": current_user.id,
            "platform_name": settings.platform_name,
            "default_palette": settings.default_palette,
            "accent": settings.accent,
        },
    )
    return settings


@router.post("/logo", response_model=SiteSettingsAdminOut)
async def upload_logo(
    file: UploadFile,
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> SiteSettings:
    """Store a custom org logo that replaces the built-in mark in the lockup.
    Kept in the DB (not object storage) so branding works on the infra-free
    stack and pre-auth. Emits ``site.settings_updated`` like any branding change."""
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_LOGO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Logo must be a PNG, JPEG, WebP, GIF, or SVG image",
        )
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file"
        )
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Logo exceeds {MAX_LOGO_BYTES // (1024 * 1024)} MB limit",
        )

    settings = await get_or_create_settings(db)
    settings.logo_data = data
    settings.logo_content_type = content_type
    settings.logo_updated_at = utcnow()
    await db.commit()
    await db.refresh(settings)

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


@router.post("/export")
async def export_backup(
    body: BackupExportRequest,
    _user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    if not body.sections:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one section to export",
        )
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
    try:
        result = await backup.import_data(db, storage, body.payload, body.sections)
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


def _operational_out(settings: SiteSettings) -> OperationalSettingsOut:
    return OperationalSettingsOut(
        registration_open=settings.registration_open,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_username=settings.smtp_username,
        smtp_from=settings.smtp_from,
        smtp_starttls=settings.smtp_starttls,
        smtp_password_set=bool(settings.smtp_password),
        archive_auto_delete=settings.archive_auto_delete,
        archive_retention_days=settings.archive_retention_days,
        email_domain_allowlist_enabled=settings.email_domain_allowlist_enabled,
        allowed_email_domains=settings.allowed_email_domains or [],
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
    return _operational_out(await get_or_create_settings(db))


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
    await db.commit()
    await db.refresh(settings)

    await event_bus.emit(
        "site.settings_updated",
        {"user_id": current_user.id, "section": "operational"},
    )
    return _operational_out(settings)
