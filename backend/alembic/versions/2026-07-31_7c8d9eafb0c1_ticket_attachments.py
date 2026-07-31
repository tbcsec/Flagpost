"""support ticket attachments

Revision ID: 7c8d9eafb0c1
Revises: 6b7c8d9eafb0
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7c8d9eafb0c1"
down_revision = "6b7c8d9eafb0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticket_attachments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("ticket_id", sa.String(), nullable=False),
        sa.Column("message_id", sa.String(), nullable=False),
        sa.Column("uploader_user_id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["competition_id"], ["competitions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["message_id"], ["ticket_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["uploader_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ticket_attachments_competition_id",
        "ticket_attachments",
        ["competition_id"],
    )
    op.create_index(
        "ix_ticket_attachments_ticket_id", "ticket_attachments", ["ticket_id"]
    )
    op.create_index(
        "ix_ticket_attachments_message_id", "ticket_attachments", ["message_id"]
    )
    # UNIQUE index (not a constraint + separate index) so this matches the
    # schema the test suite builds from Base.metadata, where the column is
    # declared `unique=True, index=True`. The suite never runs migrations
    # (ADR-0006), so a divergence here would be invisible in CI.
    op.create_index(
        "ix_ticket_attachments_object_key",
        "ticket_attachments",
        ["object_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("ticket_attachments")
