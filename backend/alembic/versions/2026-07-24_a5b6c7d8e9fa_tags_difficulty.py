"""challenge tags + difficulty (per-competition managed vocab)

Revision ID: a5b6c7d8e9fa
Revises: f4a5b6c7d8e9
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a5b6c7d8e9fa"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("competitions") as batch:
        batch.add_column(sa.Column("challenge_tags", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("difficulty_tiers", sa.JSON(), nullable=True))
    with op.batch_alter_table("challenges") as batch:
        batch.add_column(sa.Column("tags", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("difficulty", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("challenges") as batch:
        batch.drop_column("difficulty")
        batch.drop_column("tags")
    with op.batch_alter_table("competitions") as batch:
        batch.drop_column("difficulty_tiers")
        batch.drop_column("challenge_tags")
