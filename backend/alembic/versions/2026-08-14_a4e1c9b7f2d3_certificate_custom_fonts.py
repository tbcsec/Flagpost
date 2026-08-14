"""certificate custom fonts — organiser-uploaded typefaces (#219)

Adds ``certificate_fonts``: a per-competition font an organiser uploads (a
company's proprietary/brand typeface) to render that competition's certificates
with. Fonts are stored in object storage (this competition's namespace) and
referenced by an element as ``font="custom:<id>"``; nothing is bundled or
redistributed. New table, so there is no backfill.

Revision ID: a4e1c9b7f2d3
Revises: f3b8c21d9e07
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a4e1c9b7f2d3"
down_revision = "f3b8c21d9e07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "certificate_fonts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column("format", sa.String(), nullable=False, server_default="ttf"),
        sa.ForeignKeyConstraint(
            ["competition_id"],
            ["competitions.id"],
            name="fk_certificate_fonts_competition_id_competitions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_certificate_fonts"),
    )
    op.create_index(
        "ix_certificate_fonts_competition_id",
        "certificate_fonts",
        ["competition_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_certificate_fonts_competition_id", table_name="certificate_fonts"
    )
    op.drop_table("certificate_fonts")
