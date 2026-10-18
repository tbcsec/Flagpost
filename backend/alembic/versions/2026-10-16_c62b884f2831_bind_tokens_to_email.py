"""email_verification_tokens.email + password_reset_tokens.email (GHSA-42m4-hhxj-7w3m)

Binds verification and password-reset tokens to the address they were mailed
to, so redeeming one only ever acts on that address — never on whatever the
account was switched to in the meantime. Nullable: tokens minted before these
columns existed carry no address, and their redemption endpoints refuse them
(the user requests a fresh link).

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

_TABLES = ("email_verification_tokens", "password_reset_tokens")


def upgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("email", sa.String(), nullable=True))


def downgrade() -> None:
    for table in reversed(_TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("email")
