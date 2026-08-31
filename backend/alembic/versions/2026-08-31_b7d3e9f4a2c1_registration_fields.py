"""per-competition custom registration fields (#350)

Two tenant-scoped tables (ARCHITECTURE.md §6.2):

- ``registration_fields`` — operator-defined field definitions (key, label, type,
  options, required, order), one set per competition.
- ``registration_field_values`` — per-subject values (a JSON dict keyed by field
  ``key``), one row per (competition, subject) — subject_id is a plain string
  (user_id or team_id by mode), the BracketMembership idiom.

Both cascade-delete with their competition (``CompetitionScopedMixin``). New
tables, so ``op.create_table``; nothing reads them until the #350 code ships.

Revision ID: b7d3e9f4a2c1
Revises: a1b2c9d7e4f6
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7d3e9f4a2c1"
down_revision = "a1b2c9d7e4f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registration_fields",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("field_type", sa.String(), nullable=False, server_default="text"),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["competition_id"], ["competitions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "competition_id", "key", name="uq_registration_field_key"
        ),
    )
    op.create_index(
        op.f("ix_registration_fields_competition_id"),
        "registration_fields",
        ["competition_id"],
    )
    op.create_table(
        "registration_field_values",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["competition_id"], ["competitions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "competition_id", "subject_id", name="uq_registration_values_subject"
        ),
    )
    op.create_index(
        op.f("ix_registration_field_values_competition_id"),
        "registration_field_values",
        ["competition_id"],
    )
    op.create_index(
        op.f("ix_registration_field_values_subject_id"),
        "registration_field_values",
        ["subject_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_registration_field_values_subject_id"),
        table_name="registration_field_values",
    )
    op.drop_index(
        op.f("ix_registration_field_values_competition_id"),
        table_name="registration_field_values",
    )
    op.drop_table("registration_field_values")
    op.drop_index(
        op.f("ix_registration_fields_competition_id"),
        table_name="registration_fields",
    )
    op.drop_table("registration_fields")
