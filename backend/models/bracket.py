"""Bracket membership (Phase 9, Group C) — a subject's chosen division.

Brackets (e.g. "Students" vs "Open") let a competition run parallel rankings.
A subject **self-selects** its bracket at join; the choice is stored keyed by
the scoring **subject id** — the team id in team-mode, the user id in
individual-mode — exactly how ``utils/scoreboard`` groups the board, so one
table serves both modes and the scoreboard can label/filter each entry.

``subject_id`` is intentionally a plain string, not a polymorphic FK (it points
at a team *or* a user); an orphaned row (subject gone) is harmless — the board
only ever joins it against subjects that still exist. Competition-scoped so it
cascades on competition delete.
"""

from uuid import uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin


class BracketMembership(Base, TimestampMixin):
    __tablename__ = "bracket_memberships"
    __table_args__ = (
        UniqueConstraint("competition_id", "subject_id", name="uq_bracket_subject"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    competition_id: Mapped[str] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # team_id (team-mode) or user_id (individual-mode) — the §13.2 subject.
    subject_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    bracket: Mapped[str] = mapped_column(String, nullable=False)
