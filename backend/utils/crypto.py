"""Encrypted-at-rest column type for retrievable secrets (ADR-0020, issue #109).

ADR-0020 draws the line: **hash what is only ever verified, encrypt what must be
retrieved.** A password or an API token is only ever compared against, so it's
hashed and never recoverable. An OIDC ``client_secret`` has to be *sent* to the
IdP's token endpoint, and an SMTP password has to be *presented* to the mail
server — hashing them would make them useless, so they're encrypted instead.

Declared use is a column type, so a model opts in without any call-site
ceremony::

    client_secret: Mapped[str | None] = mapped_column(EncryptedString, ...)

Reads decrypt transparently; writes encrypt. Existing plaintext values are
returned as-is (see ``process_result_value``), so a column can be switched to
this type without a data migration and re-encrypts as rows are rewritten.

**Key management** follows the ADR-0019 pattern used for ``JWT_SECRET``: honour
an explicit ``SECRET_ENCRYPTION_KEY`` when set, otherwise derive a strong key
once and persist it beside the code (or at ``SECRET_ENCRYPTION_KEY_FILE``, which
compose points at the same mounted volume as the JWT secret). That keeps a
zero-config dev run working without ever shipping a key that's public in the
repo.

**Losing the key is unrecoverable by design** — that's what makes the ciphertext
worth anything. Affected secrets have to be re-entered by an administrator, so
the key file belongs in whatever gets backed up. A decrypt failure therefore
raises rather than silently returning ``None``: quietly handing back "no secret"
would turn a key mix-up into a confusing IdP or SMTP failure far from its cause.
"""

from __future__ import annotations

import logging
import os
import secrets as _secrets
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, TypeDecorator

logger = logging.getLogger("crypto")

_KEY_FILE = Path(
    os.environ.get("SECRET_ENCRYPTION_KEY_FILE")
    or (Path(__file__).resolve().parent.parent / ".secret_key")
)

# Fernet tokens are urlsafe-base64 and always start with the version byte 0x80,
# which encodes to "gAAAAA". Used to tell ciphertext from a pre-existing
# plaintext value so adopting the type needs no migration.
_FERNET_PREFIX = "gAAAAA"


def _persist_new_key() -> str:
    key = Fernet.generate_key().decode()
    _KEY_FILE.write_text(key)
    try:
        _KEY_FILE.chmod(0o600)
    except OSError:
        pass
    logger.warning(
        "SECRET_ENCRYPTION_KEY not set — generated a persistent per-install key "
        "at %s. Back this up: without it, stored secrets can't be decrypted and "
        "must be re-entered. Set SECRET_ENCRYPTION_KEY explicitly for multi-host "
        "deployments, where every replica needs the same key.",
        _KEY_FILE,
    )
    return key


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    configured = os.environ.get("SECRET_ENCRYPTION_KEY", "").strip()
    if configured:
        return Fernet(configured.encode())
    try:
        if _KEY_FILE.exists():
            existing = _KEY_FILE.read_text().strip()
            if existing:
                return Fernet(existing.encode())
        return Fernet(_persist_new_key().encode())
    except OSError:
        # Read-only filesystem. An ephemeral key still beats storing plaintext,
        # but anything written now becomes unreadable after a restart — so say
        # so loudly rather than failing mysteriously later.
        logger.error(
            "SECRET_ENCRYPTION_KEY not set and %s is unwritable — using an "
            "ephemeral key. Secrets saved now will NOT be readable after a "
            "restart. Set SECRET_ENCRYPTION_KEY.",
            _KEY_FILE,
        )
        return Fernet(Fernet.generate_key())


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


class EncryptedString(TypeDecorator):
    """A ``String`` column whose value is encrypted at rest (ADR-0020).

    Stored as text so it stays portable across SQLite and Postgres (ADR-0006)
    and survives the generic backup engine's column (de)serialiser unchanged —
    it round-trips the ciphertext, which is the correct behaviour: a backup of
    an encrypted column shouldn't contain the plaintext.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None or value == "":
            return value
        return encrypt_secret(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None or value == "":
            return value
        if not value.startswith(_FERNET_PREFIX):
            # Written before the column adopted this type. Returned as-is so
            # adoption needs no migration; it re-encrypts on the next write.
            return value
        try:
            return decrypt_secret(value)
        except InvalidToken as exc:
            raise RuntimeError(
                "Could not decrypt a stored secret — the encryption key has "
                "changed or been lost. Restore the original key file, or clear "
                "and re-enter the affected secret."
            ) from exc
