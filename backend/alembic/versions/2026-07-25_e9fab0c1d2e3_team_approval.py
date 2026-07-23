"""team join approval — approval_required flag + applications table

Revision ID: e9fab0c1d2e3
Revises: d8e9fab0c1d2
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e9fab0c1d2e3"
down_revision = "d8e9fab0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("teams") as batch:
        batch.add_column(
            sa.Column("approval_required", sa.Boolean(), nullable=False, server_default="0")
        )
    op.create_table(
        "team_join_requests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("team_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_application"),
    )
    op.create_index("ix_team_join_requests_competition_id", "team_join_requests", ["competition_id"])
    op.create_index("ix_team_join_requests_team_id", "team_join_requests", ["team_id"])
    op.create_index("ix_team_join_requests_user_id", "team_join_requests", ["user_id"])


def downgrade() -> None:
    op.drop_table("team_join_requests")
    with op.batch_alter_table("teams") as batch:
        batch.drop_column("approval_required")
