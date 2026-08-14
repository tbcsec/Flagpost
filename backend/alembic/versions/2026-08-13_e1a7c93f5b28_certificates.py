"""certificates module — templates + export jobs (#219, ADR-0027)

Creates ``certificate_templates`` (one per competition: background, drag-placed
elements as JSON, recipient rule, release schedule) and
``certificate_export_jobs`` (the async "download all as a ZIP" job). Certificates
themselves are rendered on demand and never stored (ADR-0027), so there is no
per-recipient table. Both tables are new, so there is no backfill.

Revision ID: e1a7c93f5b28
Revises: d9f4a1b2c3e5
Create Date: 2026-08-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e1a7c93f5b28"
down_revision = "d9f4a1b2c3e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "certificate_templates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "background_kind",
            sa.String(),
            nullable=False,
            server_default="color",
        ),
        sa.Column("background_preset", sa.String(), nullable=True),
        sa.Column("background_object_key", sa.String(), nullable=True),
        sa.Column(
            "background_color",
            sa.String(),
            nullable=False,
            server_default="#ffffff",
        ),
        sa.Column("elements", sa.JSON(), nullable=False),
        sa.Column(
            "recipient_rule", sa.String(), nullable=False, server_default="all"
        ),
        sa.Column(
            "release_mode", sa.String(), nullable=False, server_default="manual"
        ),
        sa.Column(
            "release_delay_minutes",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["competition_id"],
            ["competitions.id"],
            name="fk_certificate_templates_competition_id_competitions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_certificate_templates"),
        sa.UniqueConstraint(
            "competition_id", name="uq_certificate_templates_competition_id"
        ),
    )
    op.create_index(
        "ix_certificate_templates_competition_id",
        "certificate_templates",
        ["competition_id"],
    )

    op.create_table(
        "certificate_export_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=True),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="pending"
        ),
        sa.Column("object_key", sa.String(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rendered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["competition_id"],
            ["competitions.id"],
            name="fk_certificate_export_jobs_competition_id_competitions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name="fk_certificate_export_jobs_requested_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_certificate_export_jobs"),
    )
    op.create_index(
        "ix_certificate_export_jobs_competition_id",
        "certificate_export_jobs",
        ["competition_id"],
    )
    op.create_index(
        "ix_certificate_export_jobs_requested_by",
        "certificate_export_jobs",
        ["requested_by"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_certificate_export_jobs_requested_by",
        table_name="certificate_export_jobs",
    )
    op.drop_index(
        "ix_certificate_export_jobs_competition_id",
        table_name="certificate_export_jobs",
    )
    op.drop_table("certificate_export_jobs")
    op.drop_index(
        "ix_certificate_templates_competition_id",
        table_name="certificate_templates",
    )
    op.drop_table("certificate_templates")
