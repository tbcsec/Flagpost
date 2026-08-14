"""Certificate models (#219, ADR-0027, optional ``certificates`` module).

A :class:`CertificateTemplate` is the per-competition design an organiser
authors in the in-app editor: a background, drag-positioned elements
(tokens/text/images stored as **% of the canvas**), the recipient rule, and the
release schedule. A certificate itself is a *pure function* of (template,
recipient standing), so **nothing per-recipient is stored** — the renderer
composites a PNG on demand (ADR-0027). ``released_at`` doubles as the state flag
(null = not yet released to participants) and the scheduler's idempotency guard,
the same shape hidden hints use for scheduled publish (#213).

A :class:`CertificateExportJob` backs the organiser "download all as a ZIP"
action: rendering thousands of certificates can't be a synchronous request, so a
job row is created ``pending`` and a scheduler tick renders + zips into object
storage, handing back a link when done.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin, UtcDateTime


class CertificateTemplate(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "certificate_templates"
    # One template per competition (§6.2 tenancy — the module is per-competition).
    __table_args__ = (
        UniqueConstraint(
            "competition_id", name="uq_certificate_templates_competition_id"
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # Background source: "color" (solid `background_color`), "preset" (a bundled
    # code-drawn style named by `background_preset`), or "upload" (an admin image
    # in object storage at `background_object_key`).
    background_kind: Mapped[str] = mapped_column(
        String, nullable=False, default="color", server_default="color"
    )
    background_preset: Mapped[str | None] = mapped_column(String, nullable=True)
    background_object_key: Mapped[str | None] = mapped_column(String, nullable=True)
    background_color: Mapped[str] = mapped_column(
        String, nullable=False, default="#ffffff", server_default="#ffffff"
    )
    # Optional per-preset colour overrides (hex). Null = the preset's built-in
    # default. Two adjustable colours, mirroring the site-branding accent/base.
    preset_accent: Mapped[str | None] = mapped_column(String, nullable=True)
    preset_base: Mapped[str | None] = mapped_column(String, nullable=True)
    # The drag-positioned elements (list of dicts; validated by schemas.certificate
    # on write, bounded in count/size there so a template can't be weaponised).
    # Generic JSON stays portable across SQLite (tests) and Postgres (ADR-0006).
    elements: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Who gets a certificate: "all" participants (default), or only those who
    # solved at least one challenge ("solvers").
    recipient_rule: Mapped[str] = mapped_column(
        String, nullable=False, default="all", server_default="all"
    )
    # When participants can see their certificate: "manual" (an organiser clicks
    # release), "on_end" (competition end), or "end_delay" (end + N minutes).
    release_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="manual", server_default="manual"
    )
    release_delay_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # The instant certificates became downloadable. Null = not released yet; the
    # scheduler's `WHERE released_at IS NULL` guard makes the release tick
    # idempotent (a released template never re-fires or re-notifies).
    released_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class CertificateFont(Base, CompetitionScopedMixin, TimestampMixin):
    """An organiser-uploaded font (a company's proprietary/brand typeface),
    stored per-competition in object storage and used *only* to render this
    competition's certificates. Not bundled or redistributed — the operator is
    responsible for holding a licence to use it (surfaced in the upload UI). An
    element references it as ``font="custom:<id>"``; the renderer resolves the
    bytes from storage, so a deleted font falls back to a bundled default rather
    than breaking the render."""

    __tablename__ = "certificate_fonts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # Organiser-chosen display label shown in the font picker.
    name: Mapped[str] = mapped_column(String, nullable=False)
    # The uploaded TTF/OTF in object storage (this competition's namespace).
    object_key: Mapped[str] = mapped_column(String, nullable=False)
    # "ttf" | "otf" — drives the @font-face format() hint and the file extension.
    format: Mapped[str] = mapped_column(
        String, nullable=False, default="ttf", server_default="ttf"
    )


class CertificateExportJob(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "certificate_export_jobs"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # The organiser who requested the export (SET NULL so deleting the user keeps
    # the job row's audit trail).
    requested_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # pending → running → done | failed.
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    # The finished ZIP in object storage (set on `done`); handed back as a signed
    # URL, never a stored file path served directly.
    object_key: Mapped[str | None] = mapped_column(String, nullable=True)
    total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    rendered: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
