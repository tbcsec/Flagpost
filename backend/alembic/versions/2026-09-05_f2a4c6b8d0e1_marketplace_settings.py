"""marketplace settings singleton (#389, ADR-0040)

New table ``marketplace_settings`` — the registry + trust config singleton
(registry url, enabled, trust policy, max trust tier, operator-added trusted
keys). New table, so ``op.create_table``; the settings router lazily creates the
single row with defaults on first read (the ``AiSettings`` singleton pattern).

Revision ID: f2a4c6b8d0e1
Revises: e1a7c4b9f2d6
Create Date: 2026-09-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2a4c6b8d0e1"
down_revision = "e1a7c4b9f2d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketplace_settings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column(
            "registry_url",
            sa.String(),
            nullable=False,
            server_default="https://marketplace.flagpost.io",
        ),
        sa.Column(
            "trust_policy", sa.String(), nullable=False, server_default="verified"
        ),
        sa.Column(
            "max_trust_tier",
            sa.String(),
            nullable=False,
            server_default="declarative",
        ),
        sa.Column("trusted_keys", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("marketplace_settings")
