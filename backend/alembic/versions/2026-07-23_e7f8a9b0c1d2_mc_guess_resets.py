"""mc_guess_resets — non-destructive multiple-choice guess resets

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mc_guess_resets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("challenge_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("team_id", sa.String(), nullable=True),
        sa.Column("reset_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["competition_id"], ["competitions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["challenge_id"], ["challenges.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reset_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mc_guess_resets_competition_id", "mc_guess_resets", ["competition_id"]
    )
    op.create_index(
        "ix_mc_guess_resets_challenge_id", "mc_guess_resets", ["challenge_id"]
    )
    op.create_index("ix_mc_guess_resets_user_id", "mc_guess_resets", ["user_id"])
    op.create_index("ix_mc_guess_resets_team_id", "mc_guess_resets", ["team_id"])


def downgrade() -> None:
    op.drop_table("mc_guess_resets")
