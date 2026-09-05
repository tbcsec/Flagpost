"""Artifact trust verification (#389, ADR-0040) — the digest + ed25519 + policy core."""

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from utils.marketplace_verify import (
    Signature,
    TrustedKey,
    VerificationError,
    compute_digest,
    evaluate,
)

ARTIFACT = b"a signed content pack's bytes"


def _keypair() -> tuple[Ed25519PrivateKey, str]:
    priv = Ed25519PrivateKey.generate()
    raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return priv, base64.b64encode(raw).decode()


def _sig(priv: Ed25519PrivateKey, key_id: str = "k", data: bytes = ARTIFACT) -> Signature:
    return Signature("ed25519", key_id, base64.b64encode(priv.sign(data)).decode())


def _digest(data: bytes = ARTIFACT) -> str:
    return compute_digest(data)


def test_root_signed_passes_every_signature_policy():
    priv, pub = _keypair()
    for policy in ("official", "verified", "signed"):
        evaluate(ARTIFACT, _digest(), _sig(priv), policy=policy, root_key=pub)


def test_trusted_key_passes_signed_and_verified_but_not_official():
    priv, pub = _keypair()
    keys = [TrustedKey("pub1", pub, verified=True)]
    # signed + verified accept an operator-trusted key…
    evaluate(ARTIFACT, _digest(), _sig(priv), policy="signed", root_key=None, trusted_keys=keys)
    evaluate(ARTIFACT, _digest(), _sig(priv), policy="verified", root_key=None, trusted_keys=keys)
    # …official does not (root key only).
    with pytest.raises(VerificationError, match="official"):
        evaluate(ARTIFACT, _digest(), _sig(priv), policy="official", root_key=None, trusted_keys=keys)


def test_verified_requires_the_verified_flag():
    priv, pub = _keypair()
    unverified = [TrustedKey("pub1", pub, verified=False)]
    # 'signed' takes any trusted key; 'verified' rejects an unflagged one.
    evaluate(ARTIFACT, _digest(), _sig(priv), policy="signed", root_key=None, trusted_keys=unverified)
    with pytest.raises(VerificationError, match="verified"):
        evaluate(ARTIFACT, _digest(), _sig(priv), policy="verified", root_key=None, trusted_keys=unverified)


def test_untrusted_key_is_rejected():
    signer, _ = _keypair()          # signs the artifact
    _, other_pub = _keypair()       # the only key we trust — a different one
    with pytest.raises(VerificationError, match="not trusted"):
        evaluate(
            ARTIFACT, _digest(), _sig(signer),
            policy="signed", root_key=None, trusted_keys=[TrustedKey("other", other_pub)],
        )


def test_tampered_artifact_fails_on_digest():
    priv, pub = _keypair()
    sig = _sig(priv)  # signed over ARTIFACT
    with pytest.raises(VerificationError, match="digest"):
        evaluate(b"tampered", _digest(ARTIFACT), sig, policy="signed", root_key=pub)


def test_wrong_digest_is_rejected():
    priv, pub = _keypair()
    with pytest.raises(VerificationError, match="digest"):
        evaluate(ARTIFACT, "sha256:" + "0" * 64, _sig(priv), policy="signed", root_key=pub)


def test_unsigned_needs_the_any_policy():
    for policy in ("official", "verified", "signed"):
        with pytest.raises(VerificationError, match="unsigned"):
            evaluate(ARTIFACT, _digest(), None, policy=policy, root_key="")
    # 'any' accepts an unsigned artifact (digest still checked).
    evaluate(ARTIFACT, _digest(), None, policy="any", root_key=None)
    with pytest.raises(VerificationError, match="digest"):
        evaluate(ARTIFACT, "sha256:" + "0" * 64, None, policy="any", root_key=None)


def test_signed_policy_with_no_keys_configured_fails_closed():
    priv, _ = _keypair()
    with pytest.raises(VerificationError, match="no trusted keys"):
        evaluate(ARTIFACT, _digest(), _sig(priv), policy="signed", root_key=None, trusted_keys=[])


def test_unknown_policy_and_algorithm_rejected():
    priv, pub = _keypair()
    with pytest.raises(VerificationError, match="unknown trust policy"):
        evaluate(ARTIFACT, _digest(), _sig(priv), policy="bogus", root_key=pub)
    bad_algo = Signature("rsa", "k", "x")
    with pytest.raises(VerificationError, match="algorithm"):
        evaluate(ARTIFACT, _digest(), bad_algo, policy="signed", root_key=pub)
