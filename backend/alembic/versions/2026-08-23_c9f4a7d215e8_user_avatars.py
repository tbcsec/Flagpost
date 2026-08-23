"""user avatars — self-service profile pictures, admin-removable

Adds the avatar columns to ``users``: the image blob (always a
server-re-encoded square WebP — see ``utils/avatars``), its content type, and
``avatar_updated_at``, which doubles as the "has an avatar" flag and the
client cache-buster. Stored in the DB rather than object storage,
deliberately mirroring the site logo: the additive backup (ADR-0016) carries
avatars for free and the zero-infra dev stack needs no MinIO.

All three columns are nullable with no defaults and nothing is backfilled —
every existing account simply has no avatar, which renders exactly as before
(the initials fallback), so this migration cannot change how any current
deployment behaves.

Revision ID: c9f4a7d215e8
Revises: a4d1e93c72b5
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c9f4a7d215e8"
down_revision = "a4d1e93c72b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("avatar_data", sa.LargeBinary(), nullable=True))
        batch.add_column(
            sa.Column("avatar_content_type", sa.String(), nullable=True)
        )
        batch.add_column(
            sa.Column("avatar_updated_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("avatar_updated_at")
        batch.drop_column("avatar_content_type")
        batch.drop_column("avatar_data")
