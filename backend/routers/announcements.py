"""Announcement routes (ROADMAP #14, §4.3, #40).

Reads gate on ``challenge_view`` (competitor access to the competition — the
same gate as the scoreboard); posting/editing gates on ``announcement_create``
(§7.1). Everything is competition-scoped (§6.2). Posting emits
``announcement.published`` (§3.2); the announcements module turns that event into
the live push + the per-recipient bell notifications, so this route stays
transport-agnostic.

Scheduled announcements (#349): a future ``publish_at`` stores the row ``hidden``
and emits nothing — it's a staff-only draft until the scheduler releases it (see
``utils/automation_scheduler``), which emits the *same* ``announcement.published``
so delivery is identical to an immediate post. A scheduled draft can be edited
(``PATCH``) or cancelled (``DELETE``) until it fires — both staff-only, both
emitting ``announcement.updated`` / ``announcement.deleted`` for audit. The
published feed (``GET ""``) never shows drafts; staff manage them via
``GET /scheduled``.

Audience targeting (#40) is enforced here on read — a targeted announcement is
simply absent from the list for anyone outside its audience — through the shared
resolver in ``utils/announcements``, so read and delivery can't drift.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import ensure_aware_utc, get_db, utcnow
from models.announcement import Announcement
from models.competition import Competition
from models.user import User
from schemas.announcement import (
    AnnouncementCreate,
    AnnouncementOut,
    AnnouncementUpdate,
)
from utils.announcements import (
    list_scheduled_announcements,
    list_visible_announcements,
)
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
    return await list_visible_announcements(db, competition_id, current_user)


def _published_event(announcement: Announcement) -> dict:
    """The ``announcement.published`` payload — identical whether an announcement
    is posted immediately or released later by the scheduler (#349), so the
    delivery module and any automation can't tell the two apart. Ids stay off the
    event: the handler reads the row, and an audit entry shouldn't carry a
    recipient list."""
    return {
        "competition_id": announcement.competition_id,
        "announcement_id": announcement.id,
        "title": announcement.title,
        "body": announcement.body,
        "severity": announcement.severity,
        "audience_type": announcement.audience_type,
        "created_at": announcement.created_at.isoformat(),
    }


async def _scoped_announcement(
    db: AsyncSession, competition_id: str, announcement_id: str
) -> Announcement:
    announcement = await db.get(Announcement, announcement_id)
    if announcement is None or announcement.competition_id != competition_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found"
        )
    return announcement


@router.get("/scheduled", response_model=list[AnnouncementOut])
async def list_scheduled(
    competition_id: str,
    current_user: User = Depends(require_permission("announcement_create")),
    db: AsyncSession = Depends(get_db),
) -> list[Announcement]:
    """Pending scheduled announcements for the staff management view (#349),
    soonest-first — the drafts an author can still edit or cancel."""
    return await list_scheduled_announcements(db, competition_id)


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

    # A future publish_at makes this a staff-only draft the scheduler releases
    # later; null or a past time posts it now (#349). An immediate post stores no
    # publish_at, so it can never be mistaken for a schedule.
    publish_at = (
        ensure_aware_utc(body.publish_at) if body.publish_at is not None else None
    )
    scheduled = publish_at is not None and publish_at > utcnow()

    announcement = Announcement(
        competition_id=competition_id,
        title=body.title,
        body=body.body,
        severity=body.severity,
        audience_type=body.audience_type,
        audience_ids=body.audience_ids or None,
        created_by=current_user.id,
        hidden=scheduled,
        publish_at=publish_at if scheduled else None,
    )
    db.add(announcement)
    await db.commit()
    await db.refresh(announcement)

    # Commit before emit (the audit consumer opens its own session). A scheduled
    # draft emits nothing now — the scheduler emits announcement.published when
    # publish_at arrives, so the broadcast + notifications fire then, not now.
    if not scheduled:
        await event_bus.emit("announcement.published", _published_event(announcement))
    return announcement


@router.patch("/{announcement_id}", response_model=AnnouncementOut)
async def update_announcement(
    competition_id: str,
    announcement_id: str,
    body: AnnouncementUpdate,
    current_user: User = Depends(require_permission("announcement_create")),
    db: AsyncSession = Depends(get_db),
) -> Announcement:
    """Edit or reschedule a *still-scheduled* announcement (#349). A published one
    is already out, so it isn't editable here. Moving the time to now/past (or
    clearing it) publishes immediately and emits ``announcement.published``;
    otherwise it stays scheduled and emits ``announcement.updated`` for audit.
    Edits content and timing only — the audience stays as posted (see
    ``AnnouncementUpdate``)."""
    announcement = await _scoped_announcement(db, competition_id, announcement_id)
    if not announcement.hidden:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a scheduled announcement can be edited",
        )
    fields = body.model_fields_set
    if "title" in fields and body.title is not None:
        announcement.title = body.title
    if "body" in fields and body.body is not None:
        announcement.body = body.body
    if "severity" in fields and body.severity is not None:
        announcement.severity = body.severity
    if "publish_at" in fields:  # explicit null clears the schedule → publish now
        announcement.publish_at = (
            ensure_aware_utc(body.publish_at)
            if body.publish_at is not None
            else None
        )

    publish_now = (
        announcement.publish_at is None
        or ensure_aware_utc(announcement.publish_at) <= utcnow()
    )
    if publish_now:
        announcement.hidden = False
        announcement.publish_at = None
    await db.commit()
    await db.refresh(announcement)

    # Commit before emit. Publishing rides the same event as an immediate post.
    if publish_now:
        await event_bus.emit("announcement.published", _published_event(announcement))
    else:
        await event_bus.emit(
            "announcement.updated",
            {"competition_id": competition_id, "announcement_id": announcement.id},
        )
    return announcement


@router.delete("/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_announcement(
    competition_id: str,
    announcement_id: str,
    current_user: User = Depends(require_permission("announcement_create")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Cancel a *still-scheduled* announcement (#349). A published one has already
    reached its audience, so it isn't cancellable here."""
    announcement = await _scoped_announcement(db, competition_id, announcement_id)
    if not announcement.hidden:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a scheduled announcement can be cancelled",
        )
    await db.delete(announcement)
    await db.commit()
    await event_bus.emit(
        "announcement.deleted",
        {"competition_id": competition_id, "announcement_id": announcement_id},
    )
