"""email verification (#74)

Admin-toggleable email-verification gate: a self-registered account must
confirm its email before it can join a competition. Three pieces: the
verified-at timestamp on users (null = unverified), a hashed-token table
mirroring password_reset_tokens, and the site-wide enable flag (default off,
so an existing install's join flow is unchanged until an admin opts in).

Revision ID: 5a6b7c8d9eaf
Revises: 4f5a6b7c8d9e
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "5a6b7c8d9eaf"
down_revision = "4f5a6b7c8d9e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
        )
    with op.batch_alter_table("site_settings") as batch:
        batch.add_column(
            sa.Column(
                "email_verification_enabled",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_email_verification_token_hash"),
    )
    op.create_index(
        "ix_email_verification_tokens_user_id",
        "email_verification_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_email_verification_tokens_token_hash",
        "email_verification_tokens",
        ["token_hash"],
    )


def downgrade() -> None:
    op.drop_table("email_verification_tokens")
    with op.batch_alter_table("site_settings") as batch:
        batch.drop_column("email_verification_enabled")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("email_verified_at")
