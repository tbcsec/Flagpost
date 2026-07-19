"""Flag storage and verification helpers (ARCHITECTURE.md §13.2).

Static flags are stored as a **salted SHA-256** (per-challenge random salt),
never plaintext — server-side comparison only, and the hash never reaches the
client in any response, admin views included. The salt means a database
disclosure doesn't reduce to a single rainbow-table pass over common flag
formats.

Regex flags are necessarily stored as the pattern itself (you can't match
against a hash); the pattern is treated with the same never-serialized
discipline as the static hash.

Case-insensitivity is a per-challenge toggle: static flags are normalized
before hashing *and* before comparison; regex flags compile with IGNORECASE.

Built in Phase 4 (challenge authoring); Phase 6 (submission) reuses
``verify_flag`` so both sides can never drift apart.
"""

from __future__ import annotations

import hashlib
import re
import secrets


def make_salt() -> str:
    return secrets.token_hex(16)


def _normalize(raw: str, case_insensitive: bool) -> str:
    value = raw.strip()
    return value.lower() if case_insensitive else value


def hash_static_flag(raw: str, salt: str, case_insensitive: bool) -> str:
    normalized = _normalize(raw, case_insensitive)
    return hashlib.sha256(f"{salt}:{normalized}".encode()).hexdigest()


def verify_static_flag(
    submitted: str, salt: str, case_insensitive: bool, expected_hash: str
) -> bool:
    candidate = hash_static_flag(submitted, salt, case_insensitive)
    return secrets.compare_digest(candidate, expected_hash)


def verify_regex_flag(submitted: str, pattern: str, case_insensitive: bool) -> bool:
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        return re.fullmatch(pattern, submitted.strip(), flags) is not None
    except re.error:
        # A malformed pattern must fail closed, not 500 a submission.
        return False
