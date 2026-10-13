"""competition invite links (#427)

New table ``invite_links`` — shareable, revocable competition share links, two
capabilities (``join`` / ``view``), optional expiry + use-cap lifecycle. Purged
with the competition (CASCADE); ``created_by`` survives author deletion
(SET NULL). New table only, so plain ``op.create_table`` — no batch needed.

Revision ID: 7c3d9e1f4a8b
Revises: d4e9f1a3c6b8
Create Date: 2026-10-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7c3d9e1f4a8b"
down_revision = "d4e9f1a3c6b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invite_links",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("competition_id", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("capability", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["competition_id"], ["competitions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_invite_links_competition_id"), "invite_links", ["competition_id"]
    )
    op.create_index(
        op.f("ix_invite_links_token"), "invite_links", ["token"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_invite_links_token"), table_name="invite_links")
    op.drop_index(op.f("ix_invite_links_competition_id"), table_name="invite_links")
    op.drop_table("invite_links")
