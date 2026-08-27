"""challenge instancing — deployment specs and instance rows (#266, ADR-0036)

Creates ``challenge_deployments`` (authoring: what to run, exposure,
guardrails, flag mode — at most one per challenge) and
``challenge_instances`` (runtime: one row per provisioned copy; the row is
the provisioning job, its ``status`` walking the ADR-0036 state machine).

Purely additive: no existing table or query is touched, both tables start
empty, and nothing reads them until the instances module ships — so this
migration cannot change how any current deployment behaves (the pages
migration precedent).

The active-subject index is partial (active statuses only) and non-unique —
``per_subject_cap`` may allow more than one live instance, so the cap is a
service-transaction concern, not a schema constraint. COALESCE picks the
credited subject exactly as ``uq_submissions_awarded_subject`` does. The
status list is inlined as literals here (migrations are frozen history; the
model's tuple may grow in later revisions with their own migrations).

Revision ID: f3a8d15c92b4
Revises: e7b2c94a63d1
Create Date: 2026-08-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f3a8d15c92b4"
down_revision = "e7b2c94a63d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "challenge_deployments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "competition_id",
            sa.String(),
            sa.ForeignKey("competitions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "challenge_id",
            sa.String(),
            sa.ForeignKey("challenges.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("backend", sa.String(), nullable=False),
        sa.Column("image_ref", sa.String(), nullable=True),
        sa.Column("manifest", sa.JSON(), nullable=True),
        sa.Column("exposure", sa.String(), nullable=False, server_default="tcp"),
        sa.Column("ports", sa.JSON(), nullable=False),
        sa.Column("env", sa.JSON(), nullable=False),
        sa.Column("resource_limits", sa.JSON(), nullable=True),
        sa.Column("lifetime_s", sa.Integer(), nullable=True),
        sa.Column(
            "per_subject_cap", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "flag_mode", sa.String(), nullable=False, server_default="static"
        ),
        sa.Column("flag_template", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "challenge_instances",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "competition_id",
            sa.String(),
            sa.ForeignKey("competitions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "challenge_id",
            sa.String(),
            sa.ForeignKey("challenges.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "deployment_id",
            sa.String(),
            sa.ForeignKey("challenge_deployments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "team_id",
            sa.String(),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="requested"
        ),
        sa.Column("backend_handle", sa.String(), nullable=True),
        sa.Column("endpoints", sa.JSON(), nullable=False),
        sa.Column("flag_hash", sa.String(), nullable=True),
        sa.Column("flag_salt", sa.String(), nullable=True),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=True, index=True
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("destroyed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "extend_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("failure_reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    active = sa.text(
        "status IN ('requested', 'provisioning', 'running', 'expiring')"
    )
    op.create_index(
        "ix_challenge_instances_active_subject",
        "challenge_instances",
        [sa.text("challenge_id"), sa.text("coalesce(team_id, user_id)")],
        sqlite_where=active,
        postgresql_where=active,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_challenge_instances_active_subject", table_name="challenge_instances"
    )
    op.drop_table("challenge_instances")
    op.drop_table("challenge_deployments")
