"""ai_conversations + ai_messages (#98, ADR-0023 Phase 2)

The conversation store for the assistants: one competition-scoped conversation
per (user, assistant_type) chat, and its user/assistant turns with per-turn token
counts (the per-competition usage counter is their sum). Both cascade from their
competition and from the conversation, so a purged competition takes its
transcripts with it (retention follows the competition lifecycle).

Revision ID: a1e7c93bd42f
Revises: c4d2f8a1b9e3
Create Date: 2026-08-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1e7c93bd42f"
down_revision = "c4d2f8a1b9e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("assistant_type", sa.String(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["competition_id"], ["competitions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_conversations_competition_id"),
        "ai_conversations",
        ["competition_id"],
    )
    op.create_index(
        op.f("ix_ai_conversations_user_id"), "ai_conversations", ["user_id"]
    )

    op.create_table(
        "ai_messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["competition_id"], ["competitions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["ai_conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_messages_competition_id"), "ai_messages", ["competition_id"]
    )
    op.create_index(
        op.f("ix_ai_messages_conversation_id"), "ai_messages", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_messages_conversation_id"), table_name="ai_messages")
    op.drop_index(op.f("ix_ai_messages_competition_id"), table_name="ai_messages")
    op.drop_table("ai_messages")
    op.drop_index(op.f("ix_ai_conversations_user_id"), table_name="ai_conversations")
    op.drop_index(
        op.f("ix_ai_conversations_competition_id"), table_name="ai_conversations"
    )
    op.drop_table("ai_conversations")
