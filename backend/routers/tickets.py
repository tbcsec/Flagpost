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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.challenge import Challenge
from models.competition import Competition
from models.team import TeamMembership
from models.ticket import Ticket, TicketMessage
from models.user import User
from schemas.ticket import (
    TicketAssign,
    TicketCreate,
    TicketDetail,
    TicketOut,
    TicketReply,
)
from utils.event_bus import event_bus
from utils.tickets import (
    can_see_internal as _can_see_internal,
    list_visible_tickets,
    ticket_detail as _ticket_detail,
    visible_ticket_row,
)

router = APIRouter(
    prefix="/api/competitions/{competition_id}/tickets", tags=["tickets"]
)


@router.get("", response_model=list[TicketOut])
async def list_tickets(
    competition_id: str,
    status_filter: str | None = None,
    current_user: User = Depends(require_permission("ticket_view")),
    db: AsyncSession = Depends(get_db),
) -> list[TicketOut]:
    return await list_visible_tickets(
        db, competition_id, current_user, status_filter=status_filter
    )


async def _load_visible_ticket(
    db: AsyncSession, competition_id: str, ticket_id: str, user: User
):
    """The ticket row (or 404), enforcing competitor ownership — a thin HTTP
    wrapper over ``utils.tickets.visible_ticket_row``. Kept here (rather than
    inlined at each call site) because the ticket-attachments router imports it
    for exactly this behaviour."""
    row = await visible_ticket_row(db, competition_id, ticket_id, user)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found"
        )
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
