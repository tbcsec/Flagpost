"""instance settings singleton + per-competition instancing policy (#266)

Phase 1a of challenge instancing (ADR-0036 §5). Adds:

- ``instance_settings`` — the site-level provisioner config singleton (backend
  kind, endpoint, encrypted registry credentials, port range, default limits,
  global concurrency ceiling, egress policy). Ships empty and disabled; the
  module is inert until an operator configures a backend.
- ``competitions.instance_max_alive`` / ``instance_lifetime_s`` — per-
  competition policy overrides; NULL means "use the site defaults".

Purely additive: the singleton row is created lazily on first read (the
site_settings / ai_settings pattern), the competition columns are nullable
with no backfill, and nothing reads any of it until the module ships — so this
cannot change how a current deployment behaves.

The three RBAC permissions (manage_instance_infra / instance_launch /
instance_view / instance_manage) need **no** migration: the catalog is code,
and the startup role re-sync (auth.seed.seed_system_roles) grants them to the
built-in roles on the next boot.

Revision ID: b4e1f7a3c8d9
Revises: f3a8d15c92b4
Create Date: 2026-08-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b4e1f7a3c8d9"
down_revision = "f3a8d15c92b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instance_settings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "backend", sa.String(), nullable=False, server_default="docker"
        ),
        sa.Column("endpoint_url", sa.String(), nullable=True),
        sa.Column("public_host", sa.String(), nullable=True),
        # EncryptedString persists as text.
        sa.Column("registry_credentials", sa.String(), nullable=True),
        sa.Column(
            "tcp_port_min", sa.Integer(), nullable=False, server_default="30000"
        ),
        sa.Column(
            "tcp_port_max", sa.Integer(), nullable=False, server_default="32767"
        ),
        sa.Column(
            "default_cpu", sa.Float(), nullable=False, server_default="1"
        ),
        sa.Column(
            "default_memory_mb", sa.Integer(), nullable=False, server_default="256"
        ),
        sa.Column(
            "default_pids", sa.Integer(), nullable=False, server_default="256"
        ),
        sa.Column(
            "max_concurrent", sa.Integer(), nullable=False, server_default="100"
        ),
        sa.Column(
            "egress_policy", sa.String(), nullable=False, server_default="deny"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    with op.batch_alter_table("competitions") as batch:
        batch.add_column(
            sa.Column("instance_max_alive", sa.Integer(), nullable=True)
        )
        batch.add_column(
            sa.Column("instance_lifetime_s", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("competitions") as batch:
        batch.drop_column("instance_lifetime_s")
        batch.drop_column("instance_max_alive")
    op.drop_table("instance_settings")
