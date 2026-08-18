"""Post-event report models (#134, ADR-0030, optional ``reports`` module).

A generated report is an expensive point-in-time snapshot of a *finished*
competition, so — unlike a certificate, which is a pure function of (template,
recipient standing) and rendered on demand with nothing persisted (ADR-0027) —
each generation is a **stored, versioned artefact**. :class:`CompetitionReport`
is the job and its result rolled into one row: the requested configuration
(preset + section toggles + options), the render status, and the object-storage
keys of the produced PDF/HTML once ready. Organisers keep a history and
re-generate a new ``version`` rather than overwriting a prior one.

Rendering runs off the request path (WeasyPrint is synchronous CPU work,
ADR-0030): a row is created ``pending`` and a scheduler tick renders it and
fills the artefact keys, the same shape :class:`CertificateExportJob` uses.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin, UtcDateTime


class CompetitionReport(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "competition_reports"
    # Version is monotonic *and unique* per competition — the constraint makes the
    # invariant hold under concurrent creates (two racing max()+1 inserts can't
    # both land); the create route retries on the resulting conflict.
    __table_args__ = (
        UniqueConstraint(
            "competition_id", "version", name="uq_competition_report_version"
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # Monotonic per competition (1, 2, 3…) so the history reads as versions;
    # assigned at job creation as max(existing) + 1.
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # pending → running → ready | failed.
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    # The requested shape: {"preset": str, "sections": [str], "options": {...}}.
    # A snapshot of what was asked for, so re-rendering an old version is faithful.
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # The produced artefacts in object storage (set on `ready`); handed back as
    # signed URLs, never stored paths served directly.
    pdf_object_key: Mapped[str | None] = mapped_column(String, nullable=True)
    html_object_key: Mapped[str | None] = mapped_column(String, nullable=True)
    # The organiser who requested it (SET NULL so deleting the user keeps the
    # report's audit trail), mirroring CertificateExportJob.requested_by.
    requested_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
