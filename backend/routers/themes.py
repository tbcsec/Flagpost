"""Custom brand theme CRUD (#323, ADR-0011).

Admin-only management of the site-wide theme-preset library the Appearance
dropdown offers. The *active* theme is still selected through
``site_settings.default_palette`` (an existing control) — this router only
curates the library. Every route requires ``manage_site_settings``, the same
gate as the rest of site branding; theming is site-wide, not tenant-scoped, so
there is no ``competition_id`` here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.theme_preset import ThemePreset
from models.user import User
from schemas.theme import ThemeCreate, ThemeOut, ThemeUpdate
from utils.event_bus import event_bus

logger = logging.getLogger("themes")

router = APIRouter(prefix="/api/admin/themes", tags=["themes"])


async def _theme_or_404(db: AsyncSession, theme_id: str) -> ThemePreset:
    theme = await db.get(ThemePreset, theme_id)
    if theme is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Theme not found"
        )
    return theme


async def _active_palette(db: AsyncSession) -> str | None:
    return await db.scalar(
        select(SiteSettings.default_palette).where(SiteSettings.id == SITE_SETTINGS_ID)
    )


@router.get("", response_model=list[ThemeOut])
async def list_themes(
    _: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> list[ThemePreset]:
    rows = await db.scalars(select(ThemePreset).order_by(ThemePreset.name))
    return list(rows)


@router.post("", response_model=ThemeOut, status_code=status.HTTP_201_CREATED)
async def create_theme(
    body: ThemeCreate,
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> ThemePreset:
    if await db.get(ThemePreset, body.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A theme with that id already exists",
        )
    theme = ThemePreset(
        id=body.id,
        name=body.name,
        mode=body.mode,
        tokens=body.tokens,
        source="custom",
        created_by=current_user.id,
    )
    db.add(theme)
    await db.commit()  # commit before emit (audit consumer opens its own session)
    await db.refresh(theme)
    await event_bus.emit(
        "theme.created",
        {"theme_id": theme.id, "name": theme.name, "actor_user_id": current_user.id},
    )
    return theme


@router.put("/{theme_id}", response_model=ThemeOut)
async def update_theme(
    theme_id: str,
    body: ThemeUpdate,
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> ThemePreset:
    theme = await _theme_or_404(db, theme_id)
    # id is immutable (it's the active-theme pointer); only these three change.
    changes = body.model_dump(exclude_unset=True)
    for field in ("name", "mode", "tokens"):
        if field in changes and changes[field] is not None:
            setattr(theme, field, changes[field])
    await db.commit()
    await db.refresh(theme)
    await event_bus.emit(
        "theme.updated",
        {"theme_id": theme.id, "name": theme.name, "actor_user_id": current_user.id},
    )
    return theme


@router.delete("/{theme_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_theme(
    theme_id: str,
    current_user: User = Depends(require_permission("manage_site_settings")),
    db: AsyncSession = Depends(get_db),
) -> None:
    theme = await _theme_or_404(db, theme_id)
    # Deleting the active theme would silently revert the whole site to the
    # default palette — refuse, make the admin switch first.
    if await _active_palette(db) == theme.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This theme is the active site theme — switch to another first",
        )
    await db.delete(theme)
    await db.commit()
    await event_bus.emit(
        "theme.deleted", {"theme_id": theme_id, "actor_user_id": current_user.id}
    )
