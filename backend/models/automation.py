"""Automation engine models (ARCHITECTURE.md §5.1, ROADMAP #25).

``AutomationRule`` is the flat Trigger → Conditions → Actions record from
§5.1, verbatim. Deliberately **not** :class:`CompetitionScopedMixin`:
``competition_id`` is nullable because ``None`` means a global rule that fires
across every competition — the same nullable-tenant pattern as
``Notification``. ``conditions``/``actions`` are generic ``JSON`` for
SQLite/Postgres parity (ADR-0006); their shapes are validated by
``schemas/automation.py`` at write time, never trusted at evaluation time.

``Achievement`` backs the ``award_achievement`` action (§5.3): a badge record
"outside the normal scoring path" — it never touches the scoreboard (that's
``ScoreAdjustment``). Competition-scoped; the subject mirrors the §13.2
submission semantics (team in team-mode, user otherwise).
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin, UtcDateTime


class AutomationRule(Base, TimestampMixin):
    __tablename__ = "automation_rules"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    # A §3.2 event name, validated against utils/event_catalog.py (§5.1).
    trigger_type: Mapped[str] = mapped_column(String, index=True, nullable=False)
    # [{field, operator, value}, ...] — AND-ed at evaluation (§5.2).
    conditions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # [{type, ...config}, ...] — validated per action type at write time (§5.3).
    actions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # None = global rule (fires across every competition, §5.1).
    competition_id: Mapped[str | None] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # None = org rule; set = personal rule firing only on the owner's events,
    # restricted to notify-self (§5.1).
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )


class Achievement(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "achievements"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The awarded subject (§13.2 semantics): the user always recorded when
    # known; the credited team in team-mode.
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # The rule that awarded it, for provenance. SET NULL so deleting a rule
    # never erases the award history.
    rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="SET NULL"), nullable=True
    )
