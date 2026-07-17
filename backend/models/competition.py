"""The ``Competition`` entity — the tenancy root (ARCHITECTURE.md §6, §13.1).

Every tenant-scoped table hangs off this via ``competition_id`` (§6.2). The
entity itself is site-wide (it has no parent), so it does not use
``CompetitionScopedMixin``.

The model is defined here in the kernel/auth migration because
``RoleAssignment.competition_id`` references it (§7.5) — the tenancy root has
to exist before anything can be scoped to it. Its HTTP surface (router,
schemas) lands with the competition feature work, not here.

``participation_mode`` is a per-competition setting, not a module toggle
(§11.3): a single deployment may run some competitions team-based and others
solo at the same time. Scoring/scoreboard read it later to decide what they
rank.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin


class Competition(Base, TimestampMixin):
    __tablename__ = "competitions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # "team" | "individual" (§11.3).
    participation_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="team"
    )
