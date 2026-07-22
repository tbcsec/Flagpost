"""Score adjustment model (ARCHITECTURE.md §5.3 ``update_score``).

A signed bonus/penalty applied to a scoring subject **outside** the submission
path — the automation engine's ``update_score`` action writes these, and
``utils/scoreboard`` folds their per-subject sum into the ranked totals the
same way hint costs are folded in. The submission rows themselves are never
touched: an adjustment is its own auditable record (who/what/why), not a
retroactive edit of a solve.

Subject semantics mirror §13.2: ``team_id`` set in team-mode, ``user_id`` with
``team_id NULL`` in individual-mode — the same shape the scoreboard groups by.
"""

from uuid import uuid4

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin


class ScoreAdjustment(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "score_adjustments"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # Signed: positive = bonus, negative = penalty.
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # Provenance: the rule that made the adjustment. SET NULL so deleting a
    # rule never silently rewrites scores.
    rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="SET NULL"), nullable=True
    )
