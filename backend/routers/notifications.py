"""In-app notification routes (ARCHITECTURE.md §4.4).

A user's own notification center: list, mark-one-read, mark-all-read. These are
site-wide (not nested under a competition) because a user's notifications span
every competition they're in, plus any site-wide ones. Access needs no catalog
permission — the scope *is* ``user_id == current_user.id``; a user only ever
sees and mutates their own. Live delivery of new notifications rides the
``/ws/user/<user_id>`` room the module registers, not these endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user
from db import get_db, utcnow
from models.notification import Notification
from models.user import User
from schemas.notification import NotificationOut, UnreadCount

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

# Cap the bell's payload — the center is a recent feed, not an archive.
_LIST_LIMIT = 50


def _to_out(notification: Notification) -> NotificationOut:
    return NotificationOut(
        id=notification.id,
        type=notification.type,
        title=notification.title,
        body=notification.body,
        link=notification.link,
        competition_id=notification.competition_id,
        read=notification.read_at is not None,
        created_at=notification.created_at,
    )


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationOut]:
    rows = (
        await db.execute(
            select(Notification)
            .where(Notification.user_id == current_user.id)
            .order_by(Notification.created_at.desc())
            .limit(_LIST_LIMIT)
        )
    ).scalars().all()
    return [_to_out(n) for n in rows]


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UnreadCount:
    count = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == current_user.id,
            Notification.read_at.is_(None),
        )
    )
    return UnreadCount(unread=count or 0)


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationOut:
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        # Don't disclose another user's notification exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )
    if notification.read_at is None:
        notification.read_at = utcnow()
        await db.commit()
    return _to_out(notification)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=utcnow())
    )
    await db.commit()
