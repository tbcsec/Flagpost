"""OIDC identity providers (#58, ADR-0021)

Revision ID: 8d9eafb0c1d2
Revises: 7c8d9eafb0c1
Create Date: 2026-07-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "8d9eafb0c1d2"
down_revision = "7c8d9eafb0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oidc_providers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("issuer", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        # Encrypted at rest by utils.crypto.EncryptedString (ADR-0020); the
        # column itself is plain text holding the Fernet ciphertext.
        sa.Column("client_secret", sa.String(), nullable=True),
        sa.Column("scopes", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # UNIQUE index rather than a constraint + separate index, matching the
    # `unique=True, index=True` column declaration the test suite builds from
    # Base.metadata (the suite never runs migrations — ADR-0006).
    op.create_index("ix_oidc_providers_slug", "oidc_providers", ["slug"], unique=True)

    op.create_table(
        "user_external_identities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["oidc_providers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "subject", name="uq_external_identity"),
    )
    op.create_index(
        "ix_user_external_identities_user_id", "user_external_identities", ["user_id"]
    )
    op.create_index(
        "ix_user_external_identities_provider_id",
        "user_external_identities",
        ["provider_id"],
    )

    op.create_table(
        "oidc_login_states",
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("code_verifier", sa.String(), nullable=False),
        sa.Column("nonce", sa.String(), nullable=False),
        sa.Column("return_to", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["oidc_providers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("state"),
    )


def downgrade() -> None:
    op.drop_table("oidc_login_states")
    op.drop_table("user_external_identities")
    op.drop_table("oidc_providers")
