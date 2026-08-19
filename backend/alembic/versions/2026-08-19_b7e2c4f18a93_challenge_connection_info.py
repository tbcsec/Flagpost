"""challenge connection info — URL / host:port a competitor connects to (#262)

Adds ``challenges.connection_info``, an optional free-form string naming where a
challenge's live service lives ("nc host 1337", "https://box.example.com", or
plain instructions). The name and shape mirror ctfcli/CTFd's ``connection_info``
key verbatim so a real ``challenge.yml`` round-trips through the bulk importer.

Nullable with no server default, so **nothing is backfilled**: every existing
challenge simply has no connection info until an author sets one.

Plain ``add_column`` rather than ``batch_alter_table``: SQLite has native
``ALTER TABLE ADD COLUMN``, so no table rebuild is needed on either dialect, and
a rebuild is what cost us the expression/partial indexes healed by
``f3a9c1d7e250``. ``challenges`` carries only plain FK indexes today, so batch
would be safe here — it's simply gratuitous.

Revision ID: b7e2c4f18a93
Revises: 6c9f4a16f628
Create Date: 2026-08-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7e2c4f18a93"
down_revision = "6c9f4a16f628"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "challenges",
        sa.Column("connection_info", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("challenges", "connection_info")
