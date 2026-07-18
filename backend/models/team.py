"""Team models (ARCHITECTURE.md §13.1, ROADMAP #7).

Both tables are tenant-scoped (§6.2, ``CompetitionScopedMixin``).
``TeamMembership`` carries ``competition_id`` even though it's derivable
through the team — deliberately denormalized so the invariant "a user is in
at most one team per competition" is a database unique constraint
(``uq_team_membership_user_per_competition``), not just application logic.

``invite_code`` is how teammates join: a short random token the creator
shares out-of-band. It's returned only to members of the team, never in
public team listings.
"""

from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin


def generate_invite_code() -> str:
    return token_urlsafe(8)


class Team(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "teams"
    __table_args__ = (
        # Team names are unique within a competition, not globally (§6.2).
        UniqueConstraint(
            "competition_id", "name", name="uq_team_name_per_competition"
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    invite_code: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False,
        default=generate_invite_code,
    )


class TeamMembership(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint(
            "competition_id",
            "user_id",
            name="uq_team_membership_user_per_competition",
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    team_id: Mapped[str] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The creator is captain; useful for later team-admin actions (rename,
    # kick) without a redesign.
    is_captain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
