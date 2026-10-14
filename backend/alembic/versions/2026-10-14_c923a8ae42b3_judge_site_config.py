"""judge_settings + judge_languages (#447, ADR-0042)

The code judge's site configuration: the settings singleton (executor endpoint,
concurrency, default limits) and the language registry (a stock image plus argv
compile/run commands). Purely additive; the module ships inert, so a fresh row
reads as disabled. Neither table is backed up (see models/judge.py).

Revision ID: c923a8ae42b3
Revises: 9e5b2f7a1c4d
Create Date: 2026-10-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c923a8ae42b3"
down_revision = "9e5b2f7a1c4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "judge_settings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("executor", sa.String(), nullable=False, server_default="docker"),
        sa.Column("endpoint_url", sa.String(), nullable=True),
        sa.Column(
            "max_concurrent_judgings", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "default_time_limit_ms", sa.Integer(), nullable=False, server_default="2000"
        ),
        sa.Column(
            "default_memory_limit_mb", sa.Integer(), nullable=False, server_default="256"
        ),
        sa.Column(
            "default_output_limit_kb", sa.Integer(), nullable=False, server_default="8192"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "judge_languages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("key", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("image_ref", sa.String(), nullable=False),
        sa.Column("source_filename", sa.String(), nullable=False),
        sa.Column("compile_command", sa.JSON(), nullable=True),
        sa.Column("run_command", sa.JSON(), nullable=False),
        sa.Column("time_multiplier", sa.Float(), nullable=False, server_default="1"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("judge_languages")
    op.drop_table("judge_settings")
