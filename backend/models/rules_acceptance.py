"""Rules / code-of-conduct acceptance (issue #57).

One row = one user has accepted the *effective* rules document for one
competition (the per-competition override when set, else the site-wide text).
Competition-scoped (§6.2) and unique per ``(competition_id, user_id)`` —
mirrors ``TeamMembership``'s shape so "has this user accepted here" is a
database invariant, not application bookkeeping.

Rows are deliberately **not** tied to a text version: editing the rules does
not invalidate acceptances (owner decision, v1) — except that adding/changing
a competition's override deletes the competition's rows wholesale to force
re-acceptance of the more specific document (see ``update_competition``).
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, UtcDateTime, utcnow


class RulesAcceptance(Base, CompetitionScopedMixin):
    __tablename__ = "rules_acceptances"
    __table_args__ = (
        UniqueConstraint(
            "competition_id",
            "user_id",
            name="uq_rules_acceptance_user_per_competition",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    accepted_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, nullable=False
    )
