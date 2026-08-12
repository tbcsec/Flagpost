"""Password hashing, JWT access tokens, and refresh-session handling.

(ARCHITECTURE.md §7.7, ADR-0003.)

- Passwords: argon2 via pwdlib (a modern KDF; never reversible).
- Access token: short-lived JWT (default 15 min), ``sub`` = user id. Verified
  on every REST request and reused for the WebSocket first-frame handshake
  later — one token type across transports (ADR-0003).
- Refresh token: opaque random string handed to the client in an httpOnly
  cookie; only its SHA-256 hash is stored (``RefreshSession``), so the DB
  never holds a usable token. Rotated on every refresh and revocable on
  logout.
- API token (issue #75): a separate, long-lived opaque token (``flp_`` prefix)
  for programmatic REST access — administrator-minted, authenticates as its
  holder. REST only, not accepted at the WebSocket handshake. Same
  hash-at-rest treatment as a refresh token.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from config import settings

logger = logging.getLogger("auth.security")

# argon2id with parallelism=1 (#207): the OWASP-recommended server config —
# throughput comes from hashing many logins concurrently, not from splitting one
# hash across cores. pwdlib's default p=4 makes oversubscription unavoidable
# under multi-worker on a box where cores≈workers (N workers × p lanes). Memory
# and time stay at pwdlib's recommended values. Existing p=4 hashes still verify
# — argon2 reads its params from the encoded hash, so only new hashes use p=1.
_password_hasher = PasswordHash(
    (
        Argon2Hasher(
            memory_cost=settings.argon2_memory_cost,
            time_cost=settings.argon2_time_cost,
            parallelism=settings.argon2_parallelism,
        ),
    )
)


def _effective_cores() -> int:
    """The container's core allowance — cgroup quota (Phase 3) or host count."""
    import os

    from workers import detect_cpu_quota

    quota = detect_cpu_quota()
    return int(quota) if quota else (os.cpu_count() or 1)


# Two bounded executors, sized for two different access patterns (#207) — both
# replacing ``asyncio.to_thread``, whose default pool is ~min(32, cpu+4) threads
# *per worker* (the login-storm oversubscription: N workers × that ≫ cores):
#
# - login/register/JIT hashing is spread across the N web workers, so each
#   worker gets cores // workers slots → the total concurrent hashes across all
#   workers is ~cores. No oversubscription during a doors-open login storm.
# - a bulk import runs on a single worker and wants the whole box briefly, so it
#   gets its own cores-sized pool — it's a rare admin op, not concurrent with a
#   sustained login storm in practice.
_cores = _effective_cores()
_workers = settings.web_concurrency if settings.web_concurrency > 0 else 1
# Floor of 2 per worker, not 1: a single hash thread per worker head-of-lines
# the whole worker's logins during a storm (one in-flight hash blocks the rest),
# which was worse than the mild 2x lane oversubscription two threads cause with
# p=1. Only bites when workers ≈ cores; otherwise cores//workers dominates.
_hash_executor = ThreadPoolExecutor(
    max_workers=max(2, _cores // _workers), thread_name_prefix="pwhash"
)
_bulk_hash_executor = ThreadPoolExecutor(
    max_workers=_cores, thread_name_prefix="pwhash-bulk"
)


# --- Passwords --------------------------------------------------------------

def hash_password(raw: str) -> str:
    """Synchronous hash — for one-off / non-async callers (change-password,
    seed, tests). Hot async paths use :func:`ahash_password`."""
    return _password_hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _password_hasher.verify(raw, hashed)


async def ahash_password(raw: str) -> str:
    """Hash off the event loop, on the login-bounded pool (#207)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_hash_executor, _password_hasher.hash, raw)


async def averify_password(raw: str, hashed: str) -> bool:
    """Verify off the event loop, on the login-bounded pool (#207)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _hash_executor, _password_hasher.verify, raw, hashed
    )


async def ahash_many(raws: list[str]) -> list[str]:
    """Hash a batch (mass import) concurrently on the cores-sized bulk pool,
    preserving input order (#207). Uses the whole box briefly rather than the
    per-worker login slice, so a large import still finishes under a timeout."""
    loop = asyncio.get_running_loop()
    return await asyncio.gather(
        *(loop.run_in_executor(_bulk_hash_executor, _password_hasher.hash, r) for r in raws)
    )


# --- Access tokens (JWT) ----------------------------------------------------

def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()
        ),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode + verify an access token. Raises ``jwt.PyJWTError`` if invalid."""
    payload = jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return payload


# --- Refresh tokens ---------------------------------------------------------

def generate_refresh_token() -> str:
    """A high-entropy opaque token (the raw value the client stores)."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw: str) -> str:
    """Deterministic hash for DB lookup — refresh tokens are random and
    high-entropy, so a fast hash is appropriate (unlike passwords)."""
    return hashlib.sha256(raw.encode()).hexdigest()


def refresh_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_ttl_days
    )


# --- Personal API tokens (issue #75) ----------------------------------------
#
# A distinct opaque-token format, disambiguated from a JWT access token by a
# recognizable ``flp_`` prefix (a JWT is three dot-separated base64 segments;
# this can't collide) so ``auth/deps.get_current_user`` can branch on it — and
# so a leaked token is obviously identifiable/greppable in logs. Same
# hash-at-rest treatment as a refresh token.

API_TOKEN_PREFIX = "flp_"


def generate_api_token() -> str:
    """A high-entropy opaque token (the raw value shown once, at mint time)."""
    return API_TOKEN_PREFIX + secrets.token_urlsafe(40)


def hash_api_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
