"""email_verification_tokens.email (GHSA-42m4-hhxj-7w3m)

Binds a verification token to the address it was mailed to, so redeeming it
can only ever verify that address — never whatever the account was switched to
in the meantime. Nullable: tokens minted before this column existed carry no
address, and /verify-email refuses them (the user requests a fresh link).

Revision ID: c62b884f2831
Revises: 153240a51900
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c62b884f2831"
down_revision = "153240a51900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("email_verification_tokens") as batch:
        batch.add_column(sa.Column("email", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("email_verification_tokens") as batch:
        batch.drop_column("email")
