"""Hint models (ARCHITECTURE.md §11.3, ROADMAP #15).

A ``Hint`` is attached to a challenge and revealed on request, optionally at a
point cost. Revealing is recorded per **subject** — the team in team-mode, the
user in individual-mode (the same subject scoring credits solves to, §13.2) —
so a hint one teammate unlocks is unlocked for the whole team, and the cost is
charged once per subject, never per click.

``HintReveal`` is that record: it makes reveals idempotent (a subject that has
revealed a hint isn't charged again) and gives the scoreboard the per-subject
hint-cost total to subtract from points. Reveals come from an explicit request
(charged the hint's cost) or from the automation ``release_hint`` action (§5.3,
``cost_charged=0`` — a granted hint costs nothing).
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin, UtcDateTime


class Hint(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "hints"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    challenge_id: Mapped[str] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True, nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Points deducted from the revealing subject's score. 0 = free hint.
    cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Authoring gate (#213): a hidden hint is not shown to competitors at all
    # (staff always see it), so a hint can be authored now and released later —
    # manually, on a schedule, or by the `publish_hint` automation. Default false
    # keeps every existing hint visible.
    hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Optional scheduled publish: when reached, the scheduler flips `hidden` off
    # and emits `hint.published`. Null = no schedule.
    release_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class HintReveal(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "hint_reveals"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    hint_id: Mapped[str] = mapped_column(
        ForeignKey("hints.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Denormalized so "which hints has this subject revealed on this challenge"
    # is one indexed query without joining back through hints.
    challenge_id: Mapped[str] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The account that revealed (always set); the credited team in team-mode.
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # The cost at reveal time — captured on the row so later editing a hint's
    # cost never retroactively rescores a subject that already paid.
    cost_charged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
