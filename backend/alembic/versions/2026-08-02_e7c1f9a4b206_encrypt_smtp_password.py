"""encrypt the existing plaintext smtp_password (ADR-0020, #109)

Revision ID: e7c1f9a4b206
Revises: d5b9e42c8a13
Create Date: 2026-08-02

`SiteSettings.smtp_password` becomes an `EncryptedString` column. That type's
underlying storage is still TEXT, so there is **no schema change** here — only
the one pre-existing plaintext value needs rewriting as ciphertext. New installs
have no value yet, so this no-ops for them.

The type tolerates plaintext on read and re-encrypts on the next write, so doing
nothing would also be *safe* — but the value would sit in the clear at rest until
an admin happened to re-save SMTP settings, which may be never. The owner chose a
one-shot encrypt so the single existing secret is protected the moment the
upgrade runs (#109).

This imports the app's `encrypt_secret`/`decrypt_secret` rather than reimplementing
Fernet, because the key-resolution in `utils.crypto._fernet()` must match the
running app byte-for-byte — a divergent copy here would produce ciphertext the app
can't read. The key is available at migration time: compose sets
`SECRET_ENCRYPTION_KEY_FILE` and mounts the volume before `alembic upgrade` runs.

Idempotent: the `gAAAAA` Fernet prefix marks an already-encrypted value, so a
re-run skips it. Migrations aren't covered by the test suite (ADR-0006) — verified
against real Postgres.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from utils.crypto import _FERNET_PREFIX, decrypt_secret, encrypt_secret

revision = "e7c1f9a4b206"
down_revision = "d5b9e42c8a13"
branch_labels = None
depends_on = None

_SETTINGS = sa.table(
    "site_settings",
    sa.column("id", sa.String),
    sa.column("smtp_password", sa.String),
)


def _current(conn) -> str | None:
    return conn.execute(sa.select(_SETTINGS.c.smtp_password)).scalar()


def upgrade() -> None:
    conn = op.get_bind()
    value = _current(conn)
    # None/empty → nothing to encrypt. Already-ciphertext → idempotent no-op.
    if not value or value.startswith(_FERNET_PREFIX):
        return
    conn.execute(
        _SETTINGS.update().values(smtp_password=encrypt_secret(value))
    )


def downgrade() -> None:
    # Reverting past this revision restores the plain-String column, which would
    # otherwise hand ciphertext to the SMTP server. Decrypt back to plaintext so
    # the older code keeps working. Requires the key; if it's gone this fails
    # loudly, which is correct — the value is unrecoverable without it.
    conn = op.get_bind()
    value = _current(conn)
    if not value or not value.startswith(_FERNET_PREFIX):
        return
    conn.execute(
        _SETTINGS.update().values(smtp_password=decrypt_secret(value))
    )
