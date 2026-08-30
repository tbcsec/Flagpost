"""instance kubernetes settings columns (#320)

Phase 3 of challenge instancing (ADR-0036 §1): site configuration for the
``kubernetes`` provisioner kind. Additive columns on ``instance_settings``:

- ``k8s_namespace`` — the one operator-configured namespace per-instance
  resources live in (namespace-scoped RBAC, not namespace-per-instance).
- ``k8s_bearer_token`` — ServiceAccount token (EncryptedString at the app
  layer; a plain string column here, like ``registry_credentials``).
- ``k8s_ca_cert`` — PEM CA bundle for the API server's serving cert.
- ``k8s_ingress_class`` — ``ingressClassName`` for per-instance Ingresses.
- ``k8s_image_pull_secret`` — name of an operator-created pull secret.
- ``k8s_cluster_cidr`` — comma-separated pod/service CIDRs excepted from
  NetworkPolicy ingress / egress-allow rules.

Plain ``op`` calls (native SQLite ADD/DROP COLUMN — no table rebuild), the
``d4f7a1c93e28`` pattern. Purely additive: the one non-null column carries a
server default so the existing singleton is backfilled, and nothing reads any
of these until the Phase 3 code ships.

Revision ID: f1a9d2c84b57
Revises: d4f7a1c93e28
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f1a9d2c84b57"
down_revision = "d4f7a1c93e28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "instance_settings",
        sa.Column(
            "k8s_namespace",
            sa.String(),
            nullable=False,
            server_default="flagpost-instances",
        ),
    )
    op.add_column(
        "instance_settings", sa.Column("k8s_bearer_token", sa.String(), nullable=True)
    )
    op.add_column(
        "instance_settings", sa.Column("k8s_ca_cert", sa.String(), nullable=True)
    )
    op.add_column(
        "instance_settings", sa.Column("k8s_ingress_class", sa.String(), nullable=True)
    )
    op.add_column(
        "instance_settings",
        sa.Column("k8s_image_pull_secret", sa.String(), nullable=True),
    )
    op.add_column(
        "instance_settings", sa.Column("k8s_cluster_cidr", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("instance_settings", "k8s_cluster_cidr")
    op.drop_column("instance_settings", "k8s_image_pull_secret")
    op.drop_column("instance_settings", "k8s_ingress_class")
    op.drop_column("instance_settings", "k8s_ca_cert")
    op.drop_column("instance_settings", "k8s_bearer_token")
    op.drop_column("instance_settings", "k8s_namespace")
