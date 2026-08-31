"""Announcement model (ARCHITECTURE.md §4.3, §11.3, ROADMAP #14).

A broadcast message an organiser posts to a competition, pushed live over the
§4.1 WebSocket layer rather than requiring a refresh. Tenant-scoped (§6.2): an
announcement belongs to exactly one competition and is only ever read through
that competition's scope.

Distinct from the per-user notification inbox (§4.4): announcements are a
one-to-many broadcast, not per-user read/unread state — though posting one now
*also* creates a bell notification per recipient (#40), so an announcement can't
be missed by looking away while the banner is up.

An announcement carries a **severity** (the urgency ladder) and an **audience**:
either the whole competition, or a chosen set of teams/users. Targeting is
enforced on read *and* on delivery — see ``utils/announcements``.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from db import Base, CompetitionScopedMixin, TimestampMixin, UtcDateTime

# Urgency ladder (#40). `critical` is the one tier that overrides a recipient's
# in-app notification mute (utils/notifications), so it stays deliberately
# narrow — three rungs, each with a distinct §9 token in the UI.
SEVERITIES: tuple[str, ...] = ("info", "warning", "critical")
DEFAULT_SEVERITY = "info"

# Who an announcement is for. "all" is the fast path (whole competition, one
# shared WS broadcast); "teams"/"users" resolve `audience_ids` against membership.
AUDIENCE_TYPES: tuple[str, ...] = ("all", "teams", "users")
DEFAULT_AUDIENCE = "all"


class Announcement(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "announcements"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Urgency (SEVERITIES). Drives the banner's §9 treatment, and `critical`
    # bypasses the recipient's in-app notification mute.
    severity: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_SEVERITY, server_default=DEFAULT_SEVERITY
    )
    # Audience (AUDIENCE_TYPES). "all" = the whole competition.
    audience_type: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_AUDIENCE, server_default=DEFAULT_AUDIENCE
    )
    # Team ids or user ids for a targeted announcement; null/[] when audience is
    # "all". A JSON id list, like `challenge.prerequisites` / `competition.brackets`
    # — same idiom, and the same known backup limitation (ids aren't remapped).
    audience_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Who posted it, for the audit trail. SET NULL so removing a staff account
    # doesn't erase the competition's announcement history.
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Scheduled publish (#349), mirroring the hint publish gate (#213): a hidden
    # announcement is a staff-only draft — invisible to competitors and never
    # broadcast — until the scheduler flips it visible at ``publish_at`` and emits
    # ``announcement.published``, exactly as an immediate post does. Default false
    # keeps every existing announcement visible. ``hidden`` is also the idempotent
    # guard the scheduler queries on, so a published row is never re-fired.
    hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # When a scheduled announcement should go live (UTC). Null = post immediately.
    publish_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
