"""challenge ratings (feedback module extension) + per-competition toggle

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("competitions") as batch:
        batch.add_column(
            sa.Column(
                "challenge_ratings_enabled",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )
    op.create_table(
        "challenge_ratings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("challenge_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["competition_id"], ["competitions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["challenge_id"], ["challenges.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("challenge_id", "user_id", name="uq_challenge_rating_user"),
    )
    op.create_index(
        "ix_challenge_ratings_competition_id", "challenge_ratings", ["competition_id"]
    )
    op.create_index(
        "ix_challenge_ratings_challenge_id", "challenge_ratings", ["challenge_id"]
    )
    op.create_index("ix_challenge_ratings_user_id", "challenge_ratings", ["user_id"])


def downgrade() -> None:
    op.drop_table("challenge_ratings")
    with op.batch_alter_table("competitions") as batch:
        batch.drop_column("challenge_ratings_enabled")
