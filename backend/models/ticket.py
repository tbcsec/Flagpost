"""Support ticket models (ARCHITECTURE.md §4.4, §11.3, ROADMAP #18).

A competitor opens a ``Ticket`` (optionally tied to a challenge); staff and the
opener exchange ``TicketMessage``s on its thread. Both are tenant-scoped (§6.2).

A message can be an **internal note** (``is_internal``) — visible only to staff
holding ``ticket_view_internal_notes``, never to the competitor who opened the
ticket. Nothing here is a routing engine or SLA tracker (deferred); it's the
record that replaces "ask in Discord".

A ticket of kind **question** (#450) is a competitor's question about a
challenge, asked from its page: one message, answered by the judges (privately,
or sent to everyone as a clarification). It's read-only for the competitor once
sent — a follow-up is a new question — and is marked resolved ("answered") when
a judge replies. Ordinary support tickets keep their two-way thread.
"""

from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin

TICKET_KINDS = ("support", "question")


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
    # TICKET_KINDS: a support conversation, or a question about a challenge.
    kind: Mapped[str] = mapped_column(
        String, nullable=False, default="support", server_default="support"
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
    # A staff answer that was also sent to everyone as a clarification (#450),
    # so the thread shows it and nobody sends it twice.
    sent_to_all: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # The clarification it was sent as, so the thread can show it withdrawn
    # (and stop showing the answer) once the judges take it back.
    announcement_id: Mapped[str | None] = mapped_column(
        ForeignKey("announcements.id", ondelete="SET NULL"), nullable=True
    )
