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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission, user_has_permission
from db import ensure_aware_utc, get_db, utcnow
from models.announcement import Announcement
from models.challenge import Challenge
from models.competition import Competition
from models.user import User
from routers.challenges import load_visible_challenge
from schemas.announcement import (
    AnnouncementCreate,
    AnnouncementOut,
    AnnouncementUpdate,
    ClarificationOut,
    ClarificationPost,
)
from utils.announcements import (
    clarifiable,
    list_scheduled_announcements,
    list_visible_announcements,
    published_event,
    scrub_withdrawn_answer,
    shown_body,
)
from utils.competition_status import require_playable
from utils.event_bus import event_bus

router = APIRouter(
    prefix="/api/competitions/{competition_id}/announcements", tags=["announcements"]
)
# A challenge's clarifications (#450), read where the challenge is.
clarifications_router = APIRouter(
    prefix="/api/competitions/{competition_id}", tags=["announcements"]
)


@router.get("", response_model=list[AnnouncementOut])
async def list_announcements(
    competition_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> list[AnnouncementOut]:
    rows = await list_visible_announcements(db, competition_id, current_user)
    staff = await user_has_permission(db, current_user.id, "announcement_create", competition_id)
    return [_out(a, staff=staff) for a in rows]


def _out(announcement: Announcement, *, staff: bool) -> AnnouncementOut:
    out = AnnouncementOut.model_validate(announcement)
    body = shown_body(announcement, staff=staff)
    return out if body == out.body else out.model_copy(update={"body": body})


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
        await event_bus.emit("announcement.published", published_event(announcement))
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
        await event_bus.emit("announcement.published", published_event(announcement))
    else:
        await event_bus.emit(
            "announcement.updated",
            {"competition_id": competition_id, "announcement_id": announcement.id},
        )
    return announcement


@router.post("/{announcement_id}/withdraw", response_model=AnnouncementOut)
async def withdraw_clarification(
    competition_id: str,
    announcement_id: str,
    current_user: User = Depends(require_permission("announcement_delete")),
    db: AsyncSession = Depends(get_db),
) -> AnnouncementOut:
    """Take back a clarification the judges sent (#450 follow-up). It stays
    listed, marked withdrawn — so anyone who read it knows not to rely on it —
    but its answer is no longer shown to competitors, and everyone is told.
    Ordinary announcements can't be withdrawn (owner decision)."""
    announcement = await _scoped_announcement(db, competition_id, announcement_id)
    if announcement.kind != "clarification":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only a clarification can be withdrawn"
        )
    if announcement.withdrawn_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This clarification was already withdrawn")
    announcement.withdrawn_at = utcnow()
    await scrub_withdrawn_answer(db, announcement.id)
    await db.commit()
    await db.refresh(announcement)
    # Commit before emit. The staff member is the actor, for the audit log —
    # which is why the trigger is staff-only (announcement_create).
    await event_bus.emit(
        "announcement.withdrawn",
        {
            "competition_id": competition_id,
            "announcement_id": announcement.id,
            "challenge_id": announcement.challenge_id,
            "kind": announcement.kind,
            "user_id": current_user.id,
        },
    )
    return _out(announcement, staff=True)


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


@clarifications_router.get(
    "/challenges/{challenge_id}/clarifications", response_model=list[ClarificationOut]
)
async def list_clarifications(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> list[ClarificationOut]:
    """The judges' clarifications about one challenge, newest first — gated
    like the challenge itself (a draft or unreleased challenge is a 404, and
    play must be open, as on its page)."""
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Competition not found")
    await load_visible_challenge(db, competition_id, challenge_id, current_user)
    await require_playable(db, competition, current_user.id)
    rows = await db.scalars(
        select(Announcement)
        .where(
            Announcement.competition_id == competition_id,
            Announcement.challenge_id == challenge_id,
            Announcement.kind == "clarification",
            Announcement.audience_type == "all",
            Announcement.hidden.is_(False),
        )
        .order_by(Announcement.created_at.desc())
    )
    staff = await user_has_permission(db, current_user.id, "announcement_create", competition_id)
    return [
        ClarificationOut(
            id=a.id,
            question=a.question,
            body=shown_body(a, staff=staff),
            created_at=a.created_at,
            withdrawn_at=a.withdrawn_at,
        )
        for a in rows.all()
    ]


@clarifications_router.post(
    "/challenges/{challenge_id}/clarifications",
    response_model=ClarificationOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_clarification(
    competition_id: str,
    challenge_id: str,
    body: ClarificationPost,
    current_user: User = Depends(require_permission("announcement_create")),
    db: AsyncSession = Depends(get_db),
) -> ClarificationOut:
    """A judge's clarification about a challenge with no competitor's question
    behind it — a statement fix, say (#450 follow-up). Sent to everyone, like
    an answer sent from a question."""
    competition = await db.get(Competition, competition_id)
    challenge = await db.get(Challenge, challenge_id)
    if competition is None or challenge is None or challenge.competition_id != competition_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Challenge not found")
    if not clarifiable(competition, challenge):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Competitors can't see that challenge right now, so a clarification can't be sent",
        )
    question = (body.question or "").strip() or None
    announcement = Announcement(
        competition_id=competition_id,
        kind="clarification",
        challenge_id=challenge.id,
        title=challenge.title[:200],
        question=question,
        body=body.body,
        severity="info",
        audience_type="all",
        created_by=current_user.id,
    )
    db.add(announcement)
    await db.commit()
    await db.refresh(announcement)
    await event_bus.emit("announcement.published", published_event(announcement))
    return ClarificationOut(
        id=announcement.id,
        question=announcement.question,
        body=announcement.body,
        created_at=announcement.created_at,
    )
