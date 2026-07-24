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
import secrets

import regex  # PCRE-compatible engine with a match `timeout=` (ADR-0018)

# Hard wall-clock budget for a single regex flag match (ADR-0018). Orders of
# magnitude above any honest flag check, so only catastrophic backtracking hits
# it. A staff-authored pattern is trusted to be *correct*, not to be *safe*
# against competitor-controlled input on a shared single-process runtime — this
# is the backstop that keeps one bad pattern from stalling the event loop.
REGEX_MATCH_TIMEOUT_SECONDS = 0.25


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
    """Grade a regex flag under a hard per-match timeout (ADR-0018).

    The pattern is staff-authored but ``submitted`` is competitor-controlled, and
    the backend is a single-process async runtime (ADR-0005) — so a catastrophic
    pattern (e.g. ``(a+)+$``) matched against a crafted input could otherwise burn
    the CPU indefinitely and freeze *every* request on the instance. The ``regex``
    engine honours ``timeout=`` and releases the GIL, so a runaway match is aborted
    at ``REGEX_MATCH_TIMEOUT_SECONDS``. A timeout and a malformed pattern both fail
    closed (treated as "did not match"), never a 500."""
    flags = regex.IGNORECASE if case_insensitive else 0
    try:
        return (
            regex.fullmatch(
                pattern,
                submitted.strip(),
                flags=flags,
                timeout=REGEX_MATCH_TIMEOUT_SECONDS,
            )
            is not None
        )
    except (regex.error, TimeoutError):
        return False
