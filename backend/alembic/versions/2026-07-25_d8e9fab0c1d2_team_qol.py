"""team QoL — max team size + team profile fields

Revision ID: d8e9fab0c1d2
Revises: c7d8e9fab0c1
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d8e9fab0c1d2"
down_revision = "c7d8e9fab0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("competitions") as batch:
        batch.add_column(sa.Column("max_team_size", sa.Integer(), nullable=True))
    with op.batch_alter_table("teams") as batch:
        batch.add_column(sa.Column("affiliation", sa.String(), nullable=True))
        batch.add_column(sa.Column("country", sa.String(), nullable=True))
        batch.add_column(sa.Column("website", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("teams") as batch:
        batch.drop_column("website")
        batch.drop_column("country")
        batch.drop_column("affiliation")
    with op.batch_alter_table("competitions") as batch:
        batch.drop_column("max_team_size")
