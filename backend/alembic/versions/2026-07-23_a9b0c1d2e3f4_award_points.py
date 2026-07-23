"""awards carry points + provenance (rename achievement name→title)

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a9b0c1d2e3f4"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("achievements") as batch:
        batch.alter_column("name", new_column_name="title")
        batch.add_column(
            sa.Column("points", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("awarded_by_user_id", sa.String(), nullable=True)
        )
        batch.create_foreign_key(
            batch.f("fk_achievements_awarded_by_user_id_users"),
            "users",
            ["awarded_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("achievements") as batch:
        batch.drop_constraint(
            batch.f("fk_achievements_awarded_by_user_id_users"), type_="foreignkey"
        )
        batch.drop_column("awarded_by_user_id")
        batch.drop_column("points")
        batch.alter_column("title", new_column_name="name")
