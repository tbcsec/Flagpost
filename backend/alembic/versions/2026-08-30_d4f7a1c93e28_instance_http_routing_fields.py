"""instance HTTP routing + spawn rate-limit fields (#319)

Phase 2 of challenge instancing (ADR-0036 §4). Additive columns:

- ``instance_settings.chal_base_domain`` — base domain for HTTP-exposed
  instances (``https://<token>.<chal_base_domain>``); NULL until an operator
  configures wildcard DNS + a wildcard cert.
- ``instance_settings.spawn_rate_limit`` / ``spawn_rate_window_seconds`` — the
  per-subject/per-competition launch throttle (0 = off; ADR-0036 §5).
- ``challenge_instances.subdomain`` — the per-instance HTTP routing token,
  globally UNIQUE (a FQDN is a global routing key, like a host port); NULL for
  TCP/none instances.

Uses **plain** ``op`` calls, not ``batch_alter_table``: every operation here is
a native SQLite ALTER (ADD/DROP COLUMN since 3.35, CREATE/DROP INDEX), so the
tables are never rebuilt. That matters for ``challenge_instances``, which carries
the expression-based partial index ``ix_challenge_instances_active_subject`` — a
batch rebuild would silently drop it (alembic can't reflect expression indexes),
which ``test_migrations_sqlite`` guards against. The peer index management on this
table (``f3a8d15c92b4``) uses plain ``op`` for the same reason.

Purely additive: the settings columns carry server defaults so the existing
singleton is backfilled, and ``subdomain`` is nullable — nothing reads any of
it until the Phase 2 code ships, so this can't change how a deployment behaves.

Revision ID: d4f7a1c93e28
Revises: c7e2f1a9b3d4
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4f7a1c93e28"
down_revision = "c7e2f1a9b3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "instance_settings", sa.Column("chal_base_domain", sa.String(), nullable=True)
    )
    op.add_column(
        "instance_settings",
        sa.Column("spawn_rate_limit", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "instance_settings",
        sa.Column(
            "spawn_rate_window_seconds",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
    )
    op.add_column(
        "challenge_instances", sa.Column("subdomain", sa.String(), nullable=True)
    )
    op.create_index(
        "ix_challenge_instances_subdomain",
        "challenge_instances",
        ["subdomain"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_challenge_instances_subdomain", table_name="challenge_instances"
    )
    op.drop_column("challenge_instances", "subdomain")
    op.drop_column("instance_settings", "spawn_rate_window_seconds")
    op.drop_column("instance_settings", "spawn_rate_limit")
    op.drop_column("instance_settings", "chal_base_domain")
