"""post-event reports foundation — competition_reports table (#134, ADR-0030)

Backs the optional ``reports`` module: each row is a generated post-event report
job + its result (requested config, render status, and the object-storage keys of
the produced PDF/HTML once ready). Versioned per competition so organisers keep a
history rather than overwriting. Nothing to backfill — a new table for a new,
default-on optional module; existing competitions simply have no reports yet.

Revision ID: 6c9f4a16f628
Revises: c5d9a3f21b60
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "6c9f4a16f628"
down_revision = "c5d9a3f21b60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "competition_reports",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column(
            "version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="pending"
        ),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("pdf_object_key", sa.String(), nullable=True),
        sa.Column("html_object_key", sa.String(), nullable=True),
        sa.Column("requested_by", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["competition_id"], ["competitions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_competition_reports_competition_id",
        "competition_reports",
        ["competition_id"],
    )
    op.create_index(
        "ix_competition_reports_requested_by",
        "competition_reports",
        ["requested_by"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_competition_reports_requested_by", table_name="competition_reports"
    )
    op.drop_index(
        "ix_competition_reports_competition_id", table_name="competition_reports"
    )
    op.drop_table("competition_reports")
