"""Audit log — the first and (in Tier 0) only event-bus consumer.

Every emitted event is persisted here (§3.3). Unlike tenant-scoped tables
(§6.2), ``competition_id`` is nullable: the audit log is a cross-cutting
kernel table that spans competitions, and some events (``user.registered``)
have no competition context at all. It therefore does NOT use
``CompetitionScopedMixin``.
"""

from uuid import uuid4

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin


class AuditLogEntry(Base, TimestampMixin):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    event_name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    competition_id: Mapped[str | None] = mapped_column(
        String, index=True, nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
