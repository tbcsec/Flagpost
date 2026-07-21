"""Support ticket routes (ROADMAP #18, §4.4).

Nested under the competition (§6.2). Access has two layers — a catalog
permission *and* ownership:

- Opening a ticket and replying gate on ``ticket_respond``; reading on
  ``ticket_view``. A competitor sees only their own tickets; **staff**
  (``ticket_assign``) see every ticket in the competition.
- Assign / resolve gate on ``ticket_assign``.
- **Internal notes** (``is_internal``) require ``ticket_view_internal_notes``
  to post and are stripped from a competitor's view of the thread.

Every mutation emits its §3.2 event (``ticket.created`` /
``ticket.message_posted`` / ``ticket.assigned`` / ``ticket.resolved``); the
tickets module turns those into the live-thread + staff-queue WS broadcasts and
the §4.4 audio cue, so this router stays transport-agnostic.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from auth.deps import require_permission, user_has_permission
from db import get_db
from models.challenge import Challenge
from models.competition import Competition
from models.team import Team, TeamMembership
from models.ticket import Ticket, TicketMessage
from models.user import User
from schemas.ticket import (
    TicketAssign,
    TicketCreate,
    TicketDetail,
    TicketMessageOut,
    TicketOut,
    TicketReply,
)
from utils.event_bus import event_bus

router = APIRouter(
    prefix="/api/competitions/{competition_id}/tickets", tags=["tickets"]
)


async def _is_staff(db: AsyncSession, user: User, competition_id: str) -> bool:
    return await user_has_permission(db, user.id, "ticket_assign", competition_id)


async def _can_see_internal(db: AsyncSession, user: User, competition_id: str) -> bool:
    return await user_has_permission(
        db, user.id, "ticket_view_internal_notes", competition_id
    )


async def _message_count(db: AsyncSession, ticket_id: str) -> int:
    return (
        await db.scalar(
            select(func.count(TicketMessage.id)).where(
                TicketMessage.ticket_id == ticket_id
            )
        )
    ) or 0


def _row_to_out(row, message_count: int) -> TicketOut:
    ticket, opener_name, team_name, challenge_title, assignee_name = row
    return TicketOut(
        id=ticket.id,
        subject=ticket.subject,
        status=ticket.status,
        challenge_id=ticket.challenge_id,
        challenge_title=challenge_title,
        opener_name=opener_name,
        team_name=team_name,
        assignee_name=assignee_name,
        message_count=message_count,
        created_at=ticket.created_at,
    )


def _base_select(competition_id: str):
    Opener = aliased(User)
    Assignee = aliased(User)
    return (
        select(Ticket, Opener.display_name, Team.name, Challenge.title, Assignee.display_name)
        .join(Opener, Opener.id == Ticket.opener_user_id)
        .outerjoin(Team, Team.id == Ticket.team_id)
        .outerjoin(Challenge, Challenge.id == Ticket.challenge_id)
        .outerjoin(Assignee, Assignee.id == Ticket.assignee_user_id)
        .where(Ticket.competition_id == competition_id)
    )


@router.get("", response_model=list[TicketOut])
async def list_tickets(
    competition_id: str,
    status_filter: str | None = None,
    current_user: User = Depends(require_permission("ticket_view")),
    db: AsyncSession = Depends(get_db),
) -> list[TicketOut]:
    stmt = _base_select(competition_id).order_by(Ticket.created_at.desc())
    if not await _is_staff(db, current_user, competition_id):
        # Competitors see only their own tickets.
        stmt = stmt.where(Ticket.opener_user_id == current_user.id)
    if status_filter in ("open", "resolved"):
        stmt = stmt.where(Ticket.status == status_filter)

    rows = (await db.execute(stmt)).all()
    out = []
    for row in rows:
        out.append(_row_to_out(row, await _message_count(db, row[0].id)))
    return out


async def _load_visible_ticket(
    db: AsyncSession, competition_id: str, ticket_id: str, user: User
):
    """Return the ticket row (or 404), enforcing competitor ownership."""
    row = (
        await db.execute(
            _base_select(competition_id).where(Ticket.id == ticket_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    ticket = row[0]
    if not await _is_staff(db, user, competition_id) and ticket.opener_user_id != user.id:
        # Hide someone else's ticket rather than 403 (existence not disclosed).
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return row


@router.post("", response_model=TicketDetail, status_code=status.HTTP_201_CREATED)
async def create_ticket(
    competition_id: str,
    body: TicketCreate,
    current_user: User = Depends(require_permission("ticket_respond")),
    db: AsyncSession = Depends(get_db),
) -> TicketDetail:
    if await db.get(Competition, competition_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found")
    if body.challenge_id is not None:
        challenge = await db.scalar(
            select(Challenge).where(
                Challenge.id == body.challenge_id,
                Challenge.competition_id == competition_id,
            )
        )
        if challenge is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown challenge for this competition",
            )

    membership = await db.scalar(
        select(TeamMembership).where(
            TeamMembership.competition_id == competition_id,
            TeamMembership.user_id == current_user.id,
        )
    )
    ticket = Ticket(
        competition_id=competition_id,
        subject=body.subject,
        challenge_id=body.challenge_id,
        opener_user_id=current_user.id,
        team_id=membership.team_id if membership else None,
    )
    db.add(ticket)
    await db.flush()
    db.add(
        TicketMessage(
            competition_id=competition_id,
            ticket_id=ticket.id,
            author_user_id=current_user.id,
            body=body.body,
            is_internal=False,
        )
    )
    await db.commit()

    await event_bus.emit(
        "ticket.created",
        {
            "competition_id": competition_id,
            "ticket_id": ticket.id,
            "opener_user_id": current_user.id,
            "subject": ticket.subject,
        },
    )
    return await _ticket_detail(db, competition_id, ticket.id, current_user)


@router.get("/{ticket_id}", response_model=TicketDetail)
async def get_ticket(
    competition_id: str,
    ticket_id: str,
    current_user: User = Depends(require_permission("ticket_view")),
    db: AsyncSession = Depends(get_db),
) -> TicketDetail:
    await _load_visible_ticket(db, competition_id, ticket_id, current_user)
    return await _ticket_detail(db, competition_id, ticket_id, current_user)


async def _ticket_detail(
    db: AsyncSession, competition_id: str, ticket_id: str, user: User
) -> TicketDetail:
    row = (
        await db.execute(_base_select(competition_id).where(Ticket.id == ticket_id))
    ).first()
    summary = _row_to_out(row, await _message_count(db, ticket_id))

    show_internal = await _can_see_internal(db, user, competition_id)
    msg_stmt = (
        select(TicketMessage, User.display_name)
        .join(User, User.id == TicketMessage.author_user_id)
        .where(TicketMessage.ticket_id == ticket_id)
        .order_by(TicketMessage.created_at)
    )
    if not show_internal:
        msg_stmt = msg_stmt.where(TicketMessage.is_internal.is_(False))
    messages = [
        TicketMessageOut(
            id=m.id,
            author_user_id=m.author_user_id,
            author_name=name,
            body=m.body,
            is_internal=m.is_internal,
            created_at=m.created_at,
        )
        for m, name in (await db.execute(msg_stmt)).all()
    ]
    return TicketDetail(**summary.model_dump(), messages=messages)


@router.post("/{ticket_id}/messages", response_model=TicketDetail)
async def reply_to_ticket(
    competition_id: str,
    ticket_id: str,
    body: TicketReply,
    current_user: User = Depends(require_permission("ticket_respond")),
    db: AsyncSession = Depends(get_db),
) -> TicketDetail:
    row = await _load_visible_ticket(db, competition_id, ticket_id, current_user)
    ticket = row[0]
    if body.is_internal and not await _can_see_internal(db, current_user, competition_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can't post internal notes",
        )

    db.add(
        TicketMessage(
            competition_id=competition_id,
            ticket_id=ticket_id,
            author_user_id=current_user.id,
            body=body.body,
            is_internal=body.is_internal,
        )
    )
    # A reply reopens a resolved ticket — the issue clearly isn't settled.
    if ticket.status == "resolved":
        ticket.status = "open"
    await db.commit()

    await event_bus.emit(
        "ticket.message_posted",
        {
            "competition_id": competition_id,
            "ticket_id": ticket_id,
            "author_user_id": current_user.id,
            "is_internal": body.is_internal,
        },
    )
    return await _ticket_detail(db, competition_id, ticket_id, current_user)


@router.post("/{ticket_id}/assign", response_model=TicketDetail)
async def assign_ticket(
    competition_id: str,
    ticket_id: str,
    body: TicketAssign,
    current_user: User = Depends(require_permission("ticket_assign")),
    db: AsyncSession = Depends(get_db),
) -> TicketDetail:
    ticket = (await _load_visible_ticket(db, competition_id, ticket_id, current_user))[0]
    assignee_id = body.assignee_user_id or current_user.id
    if await db.get(User, assignee_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown assignee")
    ticket.assignee_user_id = assignee_id
    await db.commit()

    await event_bus.emit(
        "ticket.assigned",
        {"competition_id": competition_id, "ticket_id": ticket_id, "assignee_user_id": assignee_id},
    )
    return await _ticket_detail(db, competition_id, ticket_id, current_user)


@router.post("/{ticket_id}/resolve", response_model=TicketDetail)
async def resolve_ticket(
    competition_id: str,
    ticket_id: str,
    current_user: User = Depends(require_permission("ticket_assign")),
    db: AsyncSession = Depends(get_db),
) -> TicketDetail:
    ticket = (await _load_visible_ticket(db, competition_id, ticket_id, current_user))[0]
    ticket.status = "resolved"
    await db.commit()

    await event_bus.emit(
        "ticket.resolved",
        {"competition_id": competition_id, "ticket_id": ticket_id},
    )
    return await _ticket_detail(db, competition_id, ticket_id, current_user)
