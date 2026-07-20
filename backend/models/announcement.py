"""Announcement model (ARCHITECTURE.md §4.3, §11.3, ROADMAP #14).

A broadcast message an organiser posts to a competition — every competitor sees
it, pushed live over the §4.1 WebSocket layer (announcement room) rather than
requiring a refresh. Tenant-scoped (§6.2): an announcement belongs to exactly
one competition and is only ever read through that competition's scope.

Distinct from the per-user notification inbox (§4.4): announcements are a
one-to-many broadcast, not per-user read/unread state.
"""

from uuid import uuid4

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin


class Announcement(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "announcements"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Who posted it, for the audit trail. SET NULL so removing a staff account
    # doesn't erase the competition's announcement history.
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
