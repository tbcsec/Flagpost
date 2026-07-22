"""Per-user dashboard layout (ARCHITECTURE.md §10.3).

A user's customized dashboard is stored as ``dashboard_layout(user_id,
dashboard_key, layout_json)`` — per-user, *not* competition-scoped: the layout
is a personal preference (like a theme override), the same whichever
competition the dashboard is viewed under. ``dashboard_key`` distinguishes
which dashboard this is (``manager`` today; ``team``/``organiser`` later, §10.3)
so a user can hold a distinct layout per audience.

The layout itself is opaque ``JSON`` — an ordered list of
``{widget_id, cols, rows, hidden}`` entries. The frontend registry (§10.1) owns
the widget catalog and the set of legitimate sizes; the backend persists the
list and does light shape/bound validation only, so adding a widget stays a
frontend-only change (the same "layout is data" split the fixed-layout Tier-2
build was built around). No saved row = fall back to the code-defined default
(§10.5); a "reset to default" simply deletes the row.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from db import Base, TimestampMixin, UtcDateTime, utcnow


class DashboardLayout(Base, TimestampMixin):
    __tablename__ = "dashboard_layouts"
    # One layout per (user, dashboard) — the natural key we upsert against.
    __table_args__ = (
        UniqueConstraint("user_id", "dashboard_key", name="uq_dashboard_layout_user_key"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # Owner. Site-wide entity (§13.1): dashboards are a personal preference, not
    # tenant data — CASCADE so a deleted user's layouts go with them.
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Which dashboard this layout is for (§10.3): "manager", later "team", etc.
    dashboard_key: Mapped[str] = mapped_column(String, nullable=False)
    # Ordered list of {widget_id, cols, rows, hidden}; opaque to the backend.
    layout_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, onupdate=utcnow, nullable=True
    )
