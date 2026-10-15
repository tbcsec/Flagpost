"""judge_problems.case_insensitive (#451)

Compare letters regardless of case — the standard ICPC/Kattis output checker's
default — so an imported problem judges as its authors intended. Existing
problems keep exact letter matching (false).

Revision ID: 716999f7cc06
Revises: fa4c1b550a0a
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "716999f7cc06"
down_revision = "fa4c1b550a0a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("judge_problems") as batch:
        batch.add_column(
            sa.Column("case_insensitive", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("judge_problems") as batch:
        batch.drop_column("case_insensitive")
