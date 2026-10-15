"""judge_problems (#447, ADR-0042)

A programming challenge's problem definition: optional limit / comparison /
language overrides (null = the default) and one test-data zip in object
storage, with a cached manifest of its test cases. At most one per challenge.
Purely additive; the table starts empty and only the judge module reads it.

Revision ID: 5aaf6f1fbe6a
Revises: c923a8ae42b3
Create Date: 2026-10-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "5aaf6f1fbe6a"
down_revision = "c923a8ae42b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "judge_problems",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "competition_id",
            sa.String(),
            sa.ForeignKey("competitions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "challenge_id",
            sa.String(),
            sa.ForeignKey("challenges.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("time_limit_ms", sa.Integer(), nullable=True),
        sa.Column("memory_limit_mb", sa.Integer(), nullable=True),
        sa.Column("output_limit_kb", sa.Integer(), nullable=True),
        sa.Column("compare_mode", sa.String(), nullable=False, server_default="token"),
        sa.Column("float_tolerance", sa.Float(), nullable=True),
        sa.Column("allowed_languages", sa.JSON(), nullable=True),
        sa.Column("object_key", sa.String(), nullable=True),
        sa.Column("testcases", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("judge_problems")
