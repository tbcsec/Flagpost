"""judge_problems.reference_language / reference_source (#451)

An imported problem package's accepted solution, kept with the problem so the
author can run it as a reference-solution check (and so an export carries one).

Revision ID: 153240a51900
Revises: 716999f7cc06
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "153240a51900"
down_revision = "716999f7cc06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("judge_problems") as batch:
        batch.add_column(sa.Column("reference_language", sa.String(), nullable=True))
        batch.add_column(sa.Column("reference_source", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("judge_problems") as batch:
        batch.drop_column("reference_source")
        batch.drop_column("reference_language")
