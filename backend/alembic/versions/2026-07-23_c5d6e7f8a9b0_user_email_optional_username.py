"""email optional + display-name as case-insensitive unique username

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-07-23

Identity change: the **display name becomes the primary login identifier** — a
username — so it gains a case-insensitive unique index, and **email becomes
optional** (unique when present; a UNIQUE column permits multiple NULLs on both
SQLite and Postgres). Login accepts the display name *or* the email.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Email: NOT NULL -> nullable. On SQLite this rebuilds the table (batch);
    # on Postgres it's a plain ALTER. The existing UNIQUE(email) is preserved.
    with op.batch_alter_table("users") as batch:
        batch.alter_column("email", existing_type=sa.String(), nullable=True)
    # Case-insensitive uniqueness for the login identifier. A functional index on
    # lower(display_name) — supported by SQLite (>=3.9) and Postgres alike.
    op.create_index(
        "uq_users_display_name_lower",
        "users",
        [sa.text("lower(display_name)")],
        unique=True,
    )


def downgrade() -> None:
    # A later SQLite batch table-rebuild drops this functional index (reflection
    # can't round-trip lower(display_name)), so it may already be gone by the time
    # a downgrade reaches here (#7) — tolerate that rather than wedging.
    try:
        op.drop_index("uq_users_display_name_lower", table_name="users")
    except sa.exc.OperationalError:
        pass
    with op.batch_alter_table("users") as batch:
        batch.alter_column("email", existing_type=sa.String(), nullable=False)
