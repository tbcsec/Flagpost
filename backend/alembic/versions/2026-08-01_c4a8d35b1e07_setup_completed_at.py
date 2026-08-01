"""record first-run completion so a live install can't be re-claimed

Revision ID: c4a8d35b1e07
Revises: b3f7c21a9d04
Create Date: 2026-08-01

The setup wizard used to gate on "does an active global Administrator exist".
That is a recoverable operator state, not a provisioning state, so an install
that lost its administrators reopened `POST /api/setup` to the public — handing
a fresh global Administrator account to any anonymous caller. `setup_completed_at`
is the durable, one-way signal that replaces it.

**The backfill is the security-critical half of this migration.** Leaving the
column NULL on an already-provisioned install would mark it as never set up and
therefore claimable — the exact vulnerability, applied to every upgrading
deployment at once. So we stamp it for any install that shows evidence of having
been used.

The chosen evidence is "at least one user row exists", which is deliberately
broader than "an active administrator exists". A banned or de-roled
administrator is precisely the state this vulnerability is reached through, and
such an install must still count as provisioned. A genuinely fresh install has
no users at all, so it correctly stays claimable and the wizard still works.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4a8d35b1e07"
down_revision = "b3f7c21a9d04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("site_settings") as batch_op:
        batch_op.add_column(
            sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True)
        )

    # Stamp existing installs as provisioned. COALESCE to created_at so the
    # timestamp reflects when the install actually began rather than when it was
    # upgraded; fall back to now() for rows predating the timestamp mixin.
    op.execute(
        """
        UPDATE site_settings
        SET setup_completed_at = COALESCE(created_at, CURRENT_TIMESTAMP)
        WHERE setup_completed_at IS NULL
          AND EXISTS (SELECT 1 FROM users)
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("site_settings") as batch_op:
        batch_op.drop_column("setup_completed_at")
