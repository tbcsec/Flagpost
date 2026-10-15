"""announcements.withdrawn_at + what a clarification reached (#450 follow-up)

The judges can take back a clarification they sent. It stays listed — marked
withdrawn, so anyone who read it knows not to rely on it — but its answer is no
longer shown to competitors. To take the answer back out of what it already
reached, ``notifications.announcement_id`` and ``ticket_messages.announcement_id``
record which announcement a bell notification and an answer sent to everyone
came from.

Revision ID: fa4c1b550a0a
Revises: 272d778c79a4
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "fa4c1b550a0a"
down_revision = "272d778c79a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("announcements") as batch:
        batch.add_column(sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("notifications") as batch:
        batch.add_column(
            sa.Column(
                "announcement_id",
                sa.String(),
                sa.ForeignKey(
                    "announcements.id",
                    ondelete="CASCADE",
                    name="fk_notifications_announcement_id_announcements",
                ),
                nullable=True,
            )
        )
        batch.create_index("ix_notifications_announcement_id", ["announcement_id"])
    with op.batch_alter_table("ticket_messages") as batch:
        batch.add_column(
            sa.Column(
                "announcement_id",
                sa.String(),
                sa.ForeignKey(
                    "announcements.id",
                    ondelete="SET NULL",
                    name="fk_ticket_messages_announcement_id_announcements",
                ),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("ticket_messages") as batch:
        batch.drop_column("announcement_id")
    with op.batch_alter_table("notifications") as batch:
        batch.drop_index("ix_notifications_announcement_id")
        batch.drop_column("announcement_id")
    with op.batch_alter_table("announcements") as batch:
        batch.drop_column("withdrawn_at")
