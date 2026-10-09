"""Artifact trust verification for the marketplace import client (#389, ADR-0040).

Pure verification logic — no DB, no network — so it is unit-testable in isolation
and is the single place the "is this artifact trustworthy?" decision is made.

Two orthogonal checks (docs/MODULES.md §7):

- **Integrity** — the artifact's bytes match the ``sha256:`` digest the catalog /
  resolution promised. Always enforced.
- **Authenticity** — a detached **ed25519** signature validates against a key the
  instance trusts, under its **trust policy**. Enforced for everything except the
  ``any`` policy (dev-only).

Signing (making artifacts) is the SDK's job (#390); this is the verify side. Keys
are raw ed25519 public keys, base64-encoded; signatures are raw 64-byte ed25519
signatures, base64-encoded. The project **root key** (first-party) is always a
candidate; the operator's **trusted keys** extend that per policy.

Trust policies, most-restrictive first:

- ``official`` — only the project root key.
- ``verified`` — root key, or a trusted key the operator flagged ``verified``.
- ``signed``   — root key, or ANY trusted key the operator added.
- ``any``      — accept even an unsigned artifact (dev/testing; loud in the UI).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

TRUST_POLICIES: tuple[str, ...] = ("official", "verified", "signed", "any")

# The synthetic key id the project root key is tracked under among the candidates.
ROOT_KEY_ID = "__root__"


class VerificationError(ValueError):
    """An artifact failed integrity or authenticity verification. The install
    route maps it to a 400 with the message."""


@dataclass(frozen=True)
class Signature:
    algorithm: str
    key_id: str
    value: str  # base64 raw ed25519 signature


@dataclass(frozen=True)
class TrustedKey:
    key_id: str
    public_key: str  # base64 raw ed25519 public key
    verified: bool = False


def compute_digest(data: bytes) -> str:
    """The artifact's content address, ``sha256:<hex>``."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def verify_digest(data: bytes, expected: str) -> None:
    actual = compute_digest(data)
    # Constant-time compare — the digest is attacker-influenced (it rides with the
    # artifact), so avoid leaking a match position via early exit.
    if not hmac.compare_digest(actual, str(expected)):
        raise VerificationError("artifact digest does not match")


def _verify_ed25519(data: bytes, signature_b64: str, public_key_b64: str) -> bool:
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        pub.verify(base64.b64decode(signature_b64), data)
        return True
    except (InvalidSignature, ValueError, TypeError):
        # ValueError/TypeError cover a malformed key/signature (wrong length, bad
        # base64) — treated as "does not validate", never a 500.
        return False


def _candidate_keys(
    policy: str,
    root_key: str | None,
    trusted_keys: list[TrustedKey],
) -> list[TrustedKey]:
    """The public keys allowed to vouch for an artifact under ``policy``."""
    candidates: list[TrustedKey] = []
    if root_key:
        candidates.append(TrustedKey(ROOT_KEY_ID, root_key, verified=True))
    if policy == "official":
        return candidates  # root only
    for key in trusted_keys:
        if policy == "verified" and not key.verified:
            continue
        candidates.append(key)
    return candidates


def evaluate(
    data: bytes,
    digest: str,
    signature: Signature | None,
    *,
    policy: str,
    root_key: str | None,
    trusted_keys: list[TrustedKey] | None = None,
) -> None:
    """Raise :class:`VerificationError` unless ``data`` is acceptable under
    ``policy``. Integrity (digest) is always checked; authenticity (signature)
    unless ``policy == "any"``."""
    if policy not in TRUST_POLICIES:
        raise VerificationError(f"unknown trust policy {policy!r}")

    verify_digest(data, digest)

    if policy == "any":
        return

    if signature is None:
        raise VerificationError(
            "artifact is unsigned, but the trust policy requires a signature"
        )
    if signature.algorithm != "ed25519":
        raise VerificationError(
            f"unsupported signature algorithm {signature.algorithm!r}"
        )

    candidates = _candidate_keys(policy, root_key, trusted_keys or [])
    if not candidates:
        raise VerificationError(
            f"no trusted keys configured for the {policy!r} trust policy"
        )
    for key in candidates:
        if _verify_ed25519(data, signature.value, key.public_key):
            return
    raise VerificationError(
        f"artifact signature is not trusted under the {policy!r} policy"
    )
