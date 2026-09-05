"""Marketplace settings (#389, ADR-0040) — the registry + trust config surface.

Admin-only GET/PUT of the ``marketplace_settings`` singleton: the registry a code
resolves against, the trust policy + trusted signing keys, the max installable
tier, and the master on/off switch. The resolve + install pipeline that consumes
this config is the next slice.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.marketplace import MARKETPLACE_SETTINGS_ID, MarketplaceSettings
from models.user import User
from schemas.marketplace import MarketplaceSettingsOut, MarketplaceSettingsUpdate
from utils.event_bus import event_bus

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


async def _get_or_create(db: AsyncSession) -> MarketplaceSettings:
    settings = await db.get(MarketplaceSettings, MARKETPLACE_SETTINGS_ID)
    if settings is None:
        settings = MarketplaceSettings(id=MARKETPLACE_SETTINGS_ID)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


def _out(settings: MarketplaceSettings) -> MarketplaceSettingsOut:
    return MarketplaceSettingsOut(
        enabled=settings.enabled,
        registry_url=settings.registry_url,
        trust_policy=settings.trust_policy,
        max_trust_tier=settings.max_trust_tier,
        trusted_keys=settings.trusted_keys or [],
    )


@router.get("/settings", response_model=MarketplaceSettingsOut)
async def get_marketplace_settings(
    _: User = Depends(require_permission("manage_marketplace")),
    db: AsyncSession = Depends(get_db),
) -> MarketplaceSettingsOut:
    return _out(await _get_or_create(db))


@router.put("/settings", response_model=MarketplaceSettingsOut)
async def update_marketplace_settings(
    body: MarketplaceSettingsUpdate,
    current_user: User = Depends(require_permission("manage_marketplace")),
    db: AsyncSession = Depends(get_db),
) -> MarketplaceSettingsOut:
    settings = await _get_or_create(db)
    changes = body.model_dump(exclude_unset=True)
    for field in ("enabled", "registry_url", "trust_policy", "max_trust_tier"):
        if field in changes and changes[field] is not None:
            setattr(settings, field, changes[field])
    if body.trusted_keys is not None:
        settings.trusted_keys = [key.model_dump() for key in body.trusted_keys]
    await db.commit()  # commit before emit (audit consumer opens its own session)
    await db.refresh(settings)
    await event_bus.emit(
        "platform.marketplace_settings_updated", {"actor_user_id": current_user.id}
    )
    return _out(settings)
