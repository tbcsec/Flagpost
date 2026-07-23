"""brackets/divisions — competition vocab + per-subject membership

Revision ID: c7d8e9fab0c1
Revises: b6c7d8e9fab0
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c7d8e9fab0c1"
down_revision = "b6c7d8e9fab0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("competitions") as batch:
        batch.add_column(sa.Column("brackets", sa.JSON(), nullable=True))
    op.create_table(
        "bracket_memberships",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("bracket", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("competition_id", "subject_id", name="uq_bracket_subject"),
    )
    op.create_index(
        "ix_bracket_memberships_competition_id", "bracket_memberships", ["competition_id"]
    )
    op.create_index(
        "ix_bracket_memberships_subject_id", "bracket_memberships", ["subject_id"]
    )


def downgrade() -> None:
    op.drop_table("bracket_memberships")
    with op.batch_alter_table("competitions") as batch:
        batch.drop_column("brackets")
