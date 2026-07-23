"""Multiple-choice guess resets (Phase 9).

A non-destructive way for staff to give a subject (or everyone) a fresh set of
guesses on a multiple-choice challenge — without deleting submission history
(analytics, audit and first-blood all stay honest). Each row is a **cutoff**: the
guess count for a subject only counts submissions made *after* the latest reset
that applies to it.

- ``user_id`` / ``team_id`` both null → a **challenge-wide** (bulk) reset that
  refreshes every subject.
- exactly one set → a **targeted** reset for that team (team-mode) or user
  (individual-mode).

``created_at`` (TimestampMixin) is the cutoff timestamp — no separate column.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin


class MCGuessReset(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "mc_guess_resets"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    challenge_id: Mapped[str] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The subject the reset applies to. Both null = a challenge-wide reset.
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # Who performed the reset, for the audit trail.
    reset_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
