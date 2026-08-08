"""multiple-choice wrong-guess point penalty (#148)

Adds the per-competition penalty percentage and the per-submission penalty
record that the dynamic re-value reads to preserve each solver's own deduction.

Revision ID: a2f4c8d1e6b7
Revises: d5b3e2c9a710
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a2f4c8d1e6b7"
down_revision = "d5b3e2c9a710"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable = off by default, so existing competitions keep unchanged scoring.
    with op.batch_alter_table("competitions") as batch:
        batch.add_column(sa.Column("mc_penalty_pct", sa.Integer(), nullable=True))
    # NOT NULL with a server_default so every existing submission back-fills to 0
    # (no penalty) — Postgres rejects a NOT NULL add without one.
    with op.batch_alter_table("submissions") as batch:
        batch.add_column(
            sa.Column(
                "mc_penalty", sa.Integer(), nullable=False, server_default="0"
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("submissions") as batch:
        batch.drop_column("mc_penalty")
    with op.batch_alter_table("competitions") as batch:
        batch.drop_column("mc_penalty_pct")
