"""ai_settings provider-config singleton (#98, ADR-0023 Phase 1)

Creates the one-row ``ai_settings`` table that holds the AI module's
bring-your-own-endpoint configuration (base_url / model / encrypted api_key /
output caps / timeout / prompt overrides / default guidance level). No data to
migrate — the module ships disabled and the row is created lazily with defaults
on first read. The conversation tables arrive with the assistants in a later
phase.

The ``api_key`` column is plain ``String`` here — ``EncryptedString.impl`` is
``String`` (it stores Fernet ciphertext as text, ADR-0020), so adopting the type
in the model needs no schema change, the same as the SMTP password.

Revision ID: c4d2f8a1b9e3
Revises: b6e8a3f5c1d9
Create Date: 2026-08-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4d2f8a1b9e3"
down_revision = "b6e8a3f5c1d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_settings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("base_url", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("api_key", sa.String(), nullable=True),
        sa.Column(
            "max_output_tokens", sa.Integer(), server_default="1024", nullable=False
        ),
        sa.Column(
            "competitor_max_output_tokens",
            sa.Integer(),
            server_default="512",
            nullable=False,
        ),
        sa.Column(
            "request_timeout_s", sa.Integer(), server_default="60", nullable=False
        ),
        sa.Column("admin_prompt_override", sa.Text(), nullable=True),
        sa.Column("competitor_prompt_override", sa.Text(), nullable=True),
        sa.Column(
            "default_guidance_level",
            sa.String(),
            server_default="platform_only",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ai_settings")
