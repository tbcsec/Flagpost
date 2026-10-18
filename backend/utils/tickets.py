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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from auth.deps import user_has_permission
from models.announcement import Announcement
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


class _ThreadStats:
    """What a ticket's summary row needs from its messages, as one caller sees
    them: how many there are, when the latest landed, and who wrote the latest
    public one."""

    __slots__ = ("count", "last_at", "last_public_author")

    def __init__(self) -> None:
        self.count = 0
        self.last_at = None
        self.last_public_author: str | None = None

    def add(self, author_id: str, created_at, is_internal: bool, include_internal: bool) -> None:
        """Fold in the next message, oldest first. Internal notes count, and move
        the activity time, only for a caller who may read them — otherwise the
        count would say a note exists that the caller can't see."""
        if not is_internal:
            self.last_public_author = author_id
        if is_internal and not include_internal:
            return
        self.count += 1
        self.last_at = created_at


async def _thread_stats(
    db: AsyncSession, competition_id: str, ticket_ids: list[str], *, include_internal: bool
) -> dict[str, _ThreadStats]:
    """One query for every listed ticket's thread (the list used to count each
    ticket separately)."""
    stats = {ticket_id: _ThreadStats() for ticket_id in ticket_ids}
    if not ticket_ids:
        return stats
    rows = await db.execute(
        select(
            TicketMessage.ticket_id,
            TicketMessage.author_user_id,
            TicketMessage.created_at,
            TicketMessage.is_internal,
        )
        .where(
            TicketMessage.competition_id == competition_id,
            TicketMessage.ticket_id.in_(ticket_ids),
        )
        .order_by(TicketMessage.created_at)
    )
    for ticket_id, author_id, created_at, is_internal in rows:
        stats[ticket_id].add(author_id, created_at, is_internal, include_internal)
    return stats


def _row_to_out(row, stats: _ThreadStats) -> TicketOut:
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
        message_count=stats.count,
        kind=ticket.kind,
        created_at=ticket.created_at,
        assignee_user_id=ticket.assignee_user_id,
        last_activity_at=stats.last_at or ticket.created_at,
        awaiting_staff=(
            ticket.status == "open"
            and stats.last_public_author == ticket.opener_user_id
        ),
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
    stats = await _thread_stats(
        db,
        competition_id,
        [row[0].id for row in rows],
        include_internal=await can_see_internal(db, user, competition_id),
    )
    return [_row_to_out(row, stats[row[0].id]) for row in rows]


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
    # The summary's figures from the thread just read — it already holds every
    # public message, and the internal ones exactly when the caller may see them.
    stats = _ThreadStats()
    for m, _ in rows:
        stats.add(m.author_user_id, m.created_at, m.is_internal, show_internal)
    summary = _row_to_out(row, stats)

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

    # Answers sent to everyone that the judges have since withdrawn (#450): the
    # thread says so, and a competitor no longer gets the text.
    withdrawn_ids: set[str] = set()
    linked = {m.announcement_id for m, _ in rows if m.announcement_id}
    if linked:
        withdrawn_ids = set(
            (
                await db.scalars(
                    select(Announcement.id).where(
                        Announcement.competition_id == competition_id,
                        Announcement.id.in_(linked),
                        Announcement.withdrawn_at.is_not(None),
                    )
                )
            ).all()
        )
    staff = await is_staff(db, user, competition_id)

    messages = [
        TicketMessageOut(
            id=m.id,
            author_user_id=m.author_user_id,
            author_name=name,
            body=(
                ""
                if m.announcement_id in withdrawn_ids and not staff
                else m.body
            ),
            is_internal=m.is_internal,
            sent_to_all=m.sent_to_all,
            withdrawn=m.announcement_id in withdrawn_ids,
            created_at=m.created_at,
            attachments=by_message.get(m.id, []),
        )
        for m, name in rows
    ]
    return TicketDetail(**summary.model_dump(), messages=messages)
