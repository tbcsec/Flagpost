"""Announcement routes (ROADMAP #14, §4.3).

Reads gate on ``challenge_view`` (competitor access to the competition — the
same gate as the scoreboard); posting gates on ``announcement_create`` (§7.1).
Everything is competition-scoped (§6.2). Posting emits ``announcement.published``
(§3.2); the announcements module turns that event into a live broadcast to the
competition's WebSocket room, so this route stays transport-agnostic.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.announcement import Announcement
from models.competition import Competition
from models.user import User
from schemas.announcement import AnnouncementCreate, AnnouncementOut
from utils.event_bus import event_bus

router = APIRouter(
    prefix="/api/competitions/{competition_id}/announcements", tags=["announcements"]
)


@router.get("", response_model=list[AnnouncementOut])
async def list_announcements(
    competition_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> list[Announcement]:
    result = await db.execute(
        select(Announcement)
        .where(Announcement.competition_id == competition_id)
        .order_by(Announcement.created_at.desc())
    )
    return list(result.scalars().all())


@router.post("", response_model=AnnouncementOut, status_code=status.HTTP_201_CREATED)
async def create_announcement(
    competition_id: str,
    body: AnnouncementCreate,
    current_user: User = Depends(require_permission("announcement_create")),
    db: AsyncSession = Depends(get_db),
) -> Announcement:
    if await db.get(Competition, competition_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )

    announcement = Announcement(
        competition_id=competition_id,
        title=body.title,
        body=body.body,
        created_by=current_user.id,
    )
    db.add(announcement)
    await db.commit()
    await db.refresh(announcement)

    await event_bus.emit(
        "announcement.published",
        {
            "competition_id": competition_id,
            "announcement_id": announcement.id,
            "title": announcement.title,
            "body": announcement.body,
            "created_at": announcement.created_at.isoformat(),
        },
    )
    return announcement
