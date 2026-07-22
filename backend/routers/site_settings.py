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

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.user import User
from schemas.site_settings import (
    SiteSettingsAdminOut,
    SiteSettingsOut,
    SiteSettingsUpdate,
)
from utils.event_bus import event_bus

router = APIRouter(prefix="/api/site-settings", tags=["site-settings"])


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
    return await get_or_create_settings(db)


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
