"""custom pages — admin-authored site-level rich-text pages (#198, ADR-0034)

Creates ``pages``: an administrator-authored page (About, Sponsors, Contact)
that appears in the sidebar and renders at ``/p/{slug}``.

Site-level on purpose — no ``competition_id`` (ADR-0034). ``content`` is
ProseMirror JSON in a generic ``JSON`` column, matching the sign-in notice and
keeping the model portable across SQLite and Postgres (ADR-0006).

Nothing is backfilled: a fresh table on an existing install means zero pages,
and the feature is invisible in the UI until an administrator authors one, so
this migration cannot change how any current deployment behaves.

``draft`` defaults to true so a page created by a future client that forgets the
field is unpublished rather than immediately live. Note the server default is
written as ``sa.text("true")`` rather than ``"1"``: Postgres rejects an integer
literal for a boolean column, and this is exactly the SQLite/Postgres divergence
the migrations job exists to catch.

Revision ID: a4d1e93c72b5
Revises: b7e2c4f18a93
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a4d1e93c72b5"
down_revision = "b7e2c4f18a93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=True),
        sa.Column(
            "icon", sa.String(), nullable=False, server_default="document"
        ),
        sa.Column(
            "nav_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "visibility",
            sa.String(),
            nullable=False,
            server_default="authenticated",
        ),
        sa.Column(
            "draft", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The slug *is* the address, so uniqueness is enforced in the database as
    # well as in the router — a race between two creates must not leave two rows
    # answering /p/{slug}. The index also serves the by-slug read, which is the
    # hot path for every page view.
    op.create_index("ix_pages_slug", "pages", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_pages_slug", table_name="pages")
    op.drop_table("pages")
