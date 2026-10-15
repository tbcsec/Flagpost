"""code_submissions + judgings + judging_runs (#448, ADR-0042)

Submitted code (the source lives in object storage), its judgings — the
``judgings`` table *is* the work queue, claimed by a conditional update — and
one row per test a judging ran. Purely additive; the tables start empty and
only the judge module reads them. Not part of the backup (runtime state, like
challenge instances): an accepted judging's score lives in its ordinary
``submissions`` row, which is.

Revision ID: 841ce13a0a92
Revises: 5aaf6f1fbe6a
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "841ce13a0a92"
down_revision = "5aaf6f1fbe6a"
branch_labels = None
depends_on = None


def _scoped() -> sa.Column:
    return sa.Column(
        "competition_id",
        sa.String(),
        sa.ForeignKey("competitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def upgrade() -> None:
    op.create_table(
        "code_submissions",
        sa.Column("id", sa.String(), primary_key=True),
        _scoped(),
        sa.Column(
            "challenge_id", sa.String(),
            sa.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column(
            "user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column(
            "team_id", sa.String(),
            sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("language_key", sa.String(), nullable=False),
        sa.Column("language_name", sa.String(), nullable=False),
        sa.Column("source_object_key", sa.String(), nullable=False),
        sa.Column("source_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "judgings",
        sa.Column("id", sa.String(), primary_key=True),
        _scoped(),
        sa.Column(
            "code_submission_id", sa.String(),
            sa.ForeignKey("code_submissions.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column(
            "challenge_id", sa.String(),
            sa.ForeignKey("challenges.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column(
            "user_id", sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column(
            "team_id", sa.String(),
            sa.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compile_output", sa.Text(), nullable=True),
        sa.Column("max_time_ms", sa.Integer(), nullable=True),
        sa.Column("max_memory_kb", sa.Integer(), nullable=True),
        sa.Column("tests_passed", sa.Integer(), nullable=True),
        sa.Column("tests_total", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "submission_id", sa.String(),
            sa.ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_judgings_status_created", "judgings", ["status", "created_at"])
    op.create_table(
        "judging_runs",
        sa.Column("id", sa.String(), primary_key=True),
        _scoped(),
        sa.Column(
            "judging_id", sa.String(),
            sa.ForeignKey("judgings.id", ondelete="CASCADE"), nullable=False, index=True,
        ),
        sa.Column("test_index", sa.Integer(), nullable=False),
        sa.Column("sample", sa.Boolean(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("time_ms", sa.Integer(), nullable=False),
        sa.Column("wall_ms", sa.Integer(), nullable=False),
        sa.Column("memory_kb", sa.Integer(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("signal", sa.Integer(), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("judging_runs")
    op.drop_index("ix_judgings_status_created", table_name="judgings")
    op.drop_table("judgings")
    op.drop_table("code_submissions")
