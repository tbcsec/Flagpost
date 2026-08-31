"""announcement scheduled publish (#349)

Scheduled announcements (ROADMAP #14): an organiser can pre-write a post and have
it go live automatically, mirroring the hint publish gate (#213). Two additive
columns on ``announcements``:

- ``hidden`` — a hidden announcement is a staff-only draft, invisible to
  competitors and never broadcast, until released. Also the idempotent guard the
  scheduler queries on. NOT NULL, server_default ``0`` so every existing
  announcement stays visible on upgrade.
- ``publish_at`` — when a scheduled announcement should go live (UTC); null =
  post immediately. At/after it, the scheduler flips ``hidden`` off and emits
  ``announcement.published`` exactly as an immediate post does.

Plain ``op.add_column`` (native SQLite ADD COLUMN, no table rebuild), the
``f1a9d2c84b57`` pattern. Purely additive; nothing reads either column until the
#349 code ships.

Revision ID: a1b2c9d7e4f6
Revises: f1a9d2c84b57
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c9d7e4f6"
down_revision = "f1a9d2c84b57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "announcements",
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "announcements",
        sa.Column("publish_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("announcements", "publish_at")
    op.drop_column("announcements", "hidden")
