"""dedupe token_hash unique constraints into unique indexes

Revision ID: b6e8a3f5c1d9
Revises: f3a9c8d1e5b2
Create Date: 2026-08-04

`password_reset_tokens` (fab0c1d2e3f4) and `email_verification_tokens`
(5a6b7c8d9eaf) were created with a named UniqueConstraint on `token_hash`
*plus* a separate non-unique `ix_` index, while the models declare
`unique=True, index=True` — which Base.metadata renders as a single UNIQUE
index. A migrated database therefore differs from the metadata schema, and
`alembic check`/autogenerate emit spurious remove_constraint/remove_index/
add_index ops on every run.

Uniqueness is enforced either way, so this is not a data-safety fix: it
collapses the constraint plus duplicate index into the single unique index
the models describe, so migrated == metadata and `alembic check` is clean.

Batch mode makes the constraint drop portable to SQLite (table recreate,
since the constraint lives in the CREATE TABLE DDL there); on Postgres it
degrades to plain ALTER TABLE / DROP INDEX / CREATE UNIQUE INDEX. Verified
against real Postgres (migrations aren't covered by the test suite,
ADR-0006).
"""

from __future__ import annotations

from alembic import op

revision = "b6e8a3f5c1d9"
down_revision = "f3a9c8d1e5b2"
branch_labels = None
depends_on = None

_TABLES = (
    (
        "password_reset_tokens",
        "uq_password_reset_token_hash",
        "ix_password_reset_tokens_token_hash",
    ),
    (
        "email_verification_tokens",
        "uq_email_verification_token_hash",
        "ix_email_verification_tokens_token_hash",
    ),
)


def upgrade() -> None:
    for table, uq, ix in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(uq, type_="unique")
            batch.drop_index(ix)
            batch.create_index(ix, ["token_hash"], unique=True)


def downgrade() -> None:
    for table, uq, ix in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_index(ix)
            batch.create_index(ix, ["token_hash"], unique=False)
            batch.create_unique_constraint(uq, ["token_hash"])
