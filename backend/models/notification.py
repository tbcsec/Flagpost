"""In-app notification model (ARCHITECTURE.md §4.4).

The baseline in-app notification center: a per-user, per-event record with
read/unread state, surfaced by the bell in the app shell and pushed live over
the ``/ws/user/<user_id>`` room. This is required-core (§11.3) and exists
independently of the automation engine's ``notify`` action — Support Tickets
needs users to notice activity before automations exist, not after. Once
automations ship (Tier 3 Phase 1), the ``notify`` action writes through the
same model/service.

A notification belongs to exactly one recipient (``user_id``) and is *not*
:class:`CompetitionScopedMixin` — ``competition_id`` is nullable so a site-wide
event (e.g. a global setting change) can notify without a tenant, mirroring how
``site.settings_updated`` carries no ``competition_id`` (§3.2).
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin, UtcDateTime


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # The recipient. Site-wide entity link (§13.1): users aren't competition-scoped.
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Optional tenant scope — null for a site-wide notification. CASCADE so a
    # competition's notifications go when it's deleted; a null-scoped one is
    # untouched (it references nothing).
    competition_id: Mapped[str | None] = mapped_column(
        ForeignKey("competitions.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # The originating event name / notification kind (e.g. "ticket.created").
    type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional in-app deep link (e.g. "/competitions/<id>/support?ticket=<id>").
    link: Mapped[str | None] = mapped_column(String, nullable=True)
    # Null = unread; set to the read timestamp when the user marks it read.
    read_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
