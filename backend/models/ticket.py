"""Support ticket models (ARCHITECTURE.md §4.4, §11.3, ROADMAP #18).

A competitor opens a ``Ticket`` (optionally tied to a challenge); staff and the
opener exchange ``TicketMessage``s on its thread. Both are tenant-scoped (§6.2).

A message can be an **internal note** (``is_internal``) — visible only to staff
holding ``ticket_view_internal_notes``, never to the competitor who opened the
ticket. Nothing here is a routing engine or SLA tracker (deferred); it's the
record that replaces "ask in Discord".
"""

from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin


class Ticket(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    subject: Mapped[str] = mapped_column(String, nullable=False)
    # "open" | "resolved". A reply reopens a resolved ticket.
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    # Optional link to the challenge the question is about.
    challenge_id: Mapped[str | None] = mapped_column(
        ForeignKey("challenges.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # The competitor who opened it — ownership gate for competitor visibility.
    opener_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The opener's team at creation (team mode), for the staff queue view.
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # The staff member handling it, if assigned.
    assignee_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TicketMessage(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "ticket_messages"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    author_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Staff-only note — never returned to a competitor (§7.1
    # ticket_view_internal_notes).
    is_internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
