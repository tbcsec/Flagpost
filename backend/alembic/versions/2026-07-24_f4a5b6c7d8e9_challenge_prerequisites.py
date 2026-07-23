"""challenge prerequisites (unlock chains)

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("challenges") as batch:
        batch.add_column(sa.Column("prerequisites", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("challenges") as batch:
        batch.drop_column("prerequisites")
