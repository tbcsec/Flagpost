"""refresh_sessions.family_id for reuse detection (GHSA-vv68)

Adds a nullable, indexed ``family_id`` to ``refresh_sessions``. Every session in
one login lineage shares it (minted at login, inherited on each rotation), so
replaying an already-revoked token can revoke the whole family — RFC 9700
§4.14.2 reuse detection.

Additive and nullable with **no backfill**: sessions minted before this column
existed have ``family_id IS NULL`` and simply don't participate in family
revocation until they next rotate (refresh rotation is frequent — a 14-day
sliding window). ``add_column`` + ``create_index`` are natively supported on both
SQLite and Postgres, so no batch mode is needed. Migrations aren't exercised by
the SQLite test suite (schema comes from ``Base.metadata``, ADR-0006) — the
Postgres migrations CI job is the check.

Revision ID: d4e9f1a3c6b8
Revises: c3f8a1b2d4e5
Create Date: 2026-09-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4e9f1a3c6b8"
down_revision = "c3f8a1b2d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "refresh_sessions",
        sa.Column("family_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_refresh_sessions_family_id",
        "refresh_sessions",
        ["family_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_refresh_sessions_family_id", table_name="refresh_sessions"
    )
    op.drop_column("refresh_sessions", "family_id")
