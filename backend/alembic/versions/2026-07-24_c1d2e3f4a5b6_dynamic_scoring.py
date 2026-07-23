"""dynamic (decay) scoring on challenges

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("challenges") as batch:
        batch.add_column(
            sa.Column(
                "scoring_type",
                sa.String(),
                nullable=False,
                server_default="static",
            )
        )
        batch.add_column(sa.Column("min_points", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("decay", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("challenges") as batch:
        batch.drop_column("decay")
        batch.drop_column("min_points")
        batch.drop_column("scoring_type")
