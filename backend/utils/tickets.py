"""Support-ticket reads shared beyond the tickets router (§4.4, §6.2).

Extracted from ``routers/tickets`` so the read paths — list, single-ticket
visibility, and the full thread detail — are callable outside an HTTP request
(the ticket-attachments router already reused them; the assistant tools will
too) without importing across routers.

These functions carry the *visibility* rules that shape what a caller may see:
a competitor sees only their own tickets, and internal notes are stripped unless
the caller holds ``ticket_view_internal_notes``. They do **not** apply the
top-level ``ticket_view`` gate — that stays a ``require_permission`` on the route
(and any non-route caller re-applies it). Nothing here raises ``HTTPException``:
:func:`visible_ticket_row` returns ``None`` for missing-or-not-visible and the
caller decides the status, so the module stays free of the request layer.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from auth.deps import user_has_permission
from models.challenge import Challenge
from models.team import Team
from models.ticket import Ticket, TicketMessage
from models.ticket_attachment import TicketAttachment
from models.user import User
from schemas.ticket import (
    TicketAttachmentOut,
    TicketDetail,
    TicketMessageOut,
    TicketOut,
)


async def is_staff(db: AsyncSession, user: User, competition_id: str) -> bool:
    return await user_has_permission(db, user.id, "ticket_assign", competition_id)


async def can_see_internal(
    db: AsyncSession, user: User, competition_id: str
) -> bool:
    return await user_has_permission(
        db, user.id, "ticket_view_internal_notes", competition_id
    )


async def message_count(db: AsyncSession, ticket_id: str) -> int:
    return (
        await db.scalar(
            select(func.count(TicketMessage.id)).where(
                TicketMessage.ticket_id == ticket_id
            )
        )
    ) or 0


def _row_to_out(row, count: int) -> TicketOut:
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
        message_count=count,
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


async def list_visible_tickets(
    db: AsyncSession,
    competition_id: str,
    user: User,
    *,
    status_filter: str | None = None,
) -> list[TicketOut]:
    """Tickets in the competition the caller may see: staff (``ticket_assign``)
    see all, a competitor sees only their own. ``status_filter`` narrows to
    ``open``/``resolved`` (any other value is ignored, as before)."""
    stmt = _base_select(competition_id).order_by(Ticket.created_at.desc())
    if not await is_staff(db, user, competition_id):
        stmt = stmt.where(Ticket.opener_user_id == user.id)
    if status_filter in ("open", "resolved"):
        stmt = stmt.where(Ticket.status == status_filter)
    rows = (await db.execute(stmt)).all()
    return [_row_to_out(row, await message_count(db, row[0].id)) for row in rows]


async def visible_ticket_row(
    db: AsyncSession, competition_id: str, ticket_id: str, user: User
):
    """The joined ticket row if the caller may see it, else ``None``.

    Enforces competitor ownership: a non-staff caller sees only their own
    ticket, and a ticket that's someone else's is reported as absent rather than
    forbidden (existence isn't disclosed).
    """
    row = (
        await db.execute(
            _base_select(competition_id).where(Ticket.id == ticket_id)
        )
    ).first()
    if row is None:
        return None
    ticket = row[0]
    if not await is_staff(db, user, competition_id) and ticket.opener_user_id != user.id:
        return None
    return row


async def ticket_detail(
    db: AsyncSession, competition_id: str, ticket_id: str, user: User
) -> TicketDetail:
    """The full thread for a ticket, with internal notes stripped unless the
    caller holds ``ticket_view_internal_notes``. Assumes the ticket exists and is
    visible — callers gate with :func:`visible_ticket_row` first (or reach here
    only for a ticket they just created / own)."""
    row = (
        await db.execute(_base_select(competition_id).where(Ticket.id == ticket_id))
    ).first()
    summary = _row_to_out(row, await message_count(db, ticket_id))

    show_internal = await can_see_internal(db, user, competition_id)
    msg_stmt = (
        select(TicketMessage, User.display_name)
        .join(User, User.id == TicketMessage.author_user_id)
        .where(TicketMessage.ticket_id == ticket_id)
        .order_by(TicketMessage.created_at)
    )
    if not show_internal:
        msg_stmt = msg_stmt.where(TicketMessage.is_internal.is_(False))
    rows = (await db.execute(msg_stmt)).all()

    # One query for the whole thread's attachments, grouped in Python — a
    # per-message query would be N+1 on a long ticket. Messages the viewer
    # can't see were already dropped above, so their images never get grouped.
    by_message: dict[str, list[TicketAttachmentOut]] = {}
    if rows:
        attachment_rows = await db.scalars(
            select(TicketAttachment)
            .where(
                TicketAttachment.competition_id == competition_id,
                TicketAttachment.message_id.in_([m.id for m, _ in rows]),
            )
            .order_by(TicketAttachment.created_at)
        )
        for a in attachment_rows:
            by_message.setdefault(a.message_id, []).append(
                TicketAttachmentOut.model_validate(a, from_attributes=True)
            )

    messages = [
        TicketMessageOut(
            id=m.id,
            author_user_id=m.author_user_id,
            author_name=name,
            body=m.body,
            is_internal=m.is_internal,
            created_at=m.created_at,
            attachments=by_message.get(m.id, []),
        )
        for m, name in rows
    ]
    return TicketDetail(**summary.model_dump(), messages=messages)
