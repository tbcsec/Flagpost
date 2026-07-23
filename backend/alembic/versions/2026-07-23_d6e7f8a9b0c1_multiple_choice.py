"""multiple-choice challenges + competition-wide guess limit

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-07-23

Adds ``challenges.choices`` (the public option list for a multiple_choice
challenge; the correct answer stays hashed in flag_hash) and
``competitions.mc_guess_limit`` (a competition-wide cap on guesses per subject per
multiple-choice challenge; null = unlimited).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("challenges") as batch:
        batch.add_column(sa.Column("choices", sa.JSON(), nullable=True))
    with op.batch_alter_table("competitions") as batch:
        batch.add_column(sa.Column("mc_guess_limit", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("competitions") as batch:
        batch.drop_column("mc_guess_limit")
    with op.batch_alter_table("challenges") as batch:
        batch.drop_column("choices")
