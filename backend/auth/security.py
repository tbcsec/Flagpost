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

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from config import settings

_password_hasher = PasswordHash.recommended()


# --- Passwords --------------------------------------------------------------

def hash_password(raw: str) -> str:
    return _password_hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _password_hasher.verify(raw, hashed)


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
