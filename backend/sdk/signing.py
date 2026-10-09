"""Module SDK — ed25519 signing (#390, ADR-0040).

The authoring counterpart to ``utils.marketplace_verify``: generate a keypair, and
sign a built artifact. Keys are raw ed25519, base64-encoded — the exact shape the
marketplace trusted-keys list and the verifier expect. A module author signs an
artifact with their private key; the operator adds the matching public key to the
marketplace ``trusted_keys``, and the install pipeline verifies it.

Only the *public* key ever leaves the author's machine (into the operator's trust
store); the private key signs and is never distributed.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_RAW = serialization.Encoding.Raw


@dataclass(frozen=True)
class KeyPair:
    public_key: str  # base64 raw ed25519 (32 bytes)
    private_key: str  # base64 raw ed25519 (32 bytes)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def generate_keypair() -> KeyPair:
    priv = Ed25519PrivateKey.generate()
    raw_priv = priv.private_bytes(
        _RAW, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    raw_pub = priv.public_key().public_bytes(_RAW, serialization.PublicFormat.Raw)
    return KeyPair(public_key=_b64(raw_pub), private_key=_b64(raw_priv))


def public_key_for(private_b64: str) -> str:
    """Derive the base64 public key from a base64 private key (so an author can
    print the value to hand the operator without storing it separately)."""
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    raw_pub = priv.public_key().public_bytes(_RAW, serialization.PublicFormat.Raw)
    return _b64(raw_pub)


def sign(data: bytes, private_b64: str, *, key_id: str = "default") -> dict:
    """Sign ``data`` and return a detached signature dict in the wire shape
    (``{algorithm, key_id, value}``) the resolve-response / verifier use."""
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    return {
        "algorithm": "ed25519",
        "key_id": key_id,
        "value": _b64(priv.sign(data)),
    }
