"""Module SDK (#390, ADR-0040) — build / sign / validate / scaffold, and the loop.

The load-bearing test is `test_built_signed_pack_installs_end_to_end`: an artifact
the SDK builds + signs must verify with the runtime verifier and parse with the
content-pack reader — i.e. the author side and the install side agree.
"""

import json

import pytest

from sdk import packaging, scaffold, signing
from sdk.cli import main
from utils.content_packs import read_pack_manifest
from utils.marketplace_verify import (
    Signature,
    TrustedKey,
    VerificationError,
    compute_digest,
    evaluate,
)


def _theme_pack(tmp_path):
    d = tmp_path / "pack"
    scaffold.init_pack(d, pack_id="you.demo", name="Demo", pack_type="theme")
    return d


def test_keygen_sign_verify_roundtrip():
    kp = signing.generate_keypair()
    data = b"some artifact bytes"
    sig = signing.sign(data, kp.private_key, key_id="k")
    evaluate(
        data, compute_digest(data), Signature(**sig),
        policy="signed", root_key=None, trusted_keys=[TrustedKey("k", kp.public_key, True)],
    )


def test_public_key_derivation():
    kp = signing.generate_keypair()
    assert signing.public_key_for(kp.private_key) == kp.public_key


def test_build_is_deterministic(tmp_path):
    d = _theme_pack(tmp_path)
    _, digest1 = packaging.build_artifact(d)
    _, digest2 = packaging.build_artifact(d)
    assert digest1 == digest2


def test_built_signed_pack_installs_end_to_end(tmp_path):
    # THE LOOP: SDK output verifies + parses on the install side.
    d = _theme_pack(tmp_path)
    data, digest = packaging.build_artifact(d)
    kp = signing.generate_keypair()
    sig = signing.sign(data, kp.private_key, key_id="you:1")
    evaluate(
        data, digest, Signature(**sig),
        policy="signed", root_key=None, trusted_keys=[TrustedKey("you:1", kp.public_key, True)],
    )
    manifest = read_pack_manifest(data)
    assert manifest.pack.pack_type.value == "theme"


def test_untrusted_signature_rejected(tmp_path):
    d = _theme_pack(tmp_path)
    data, digest = packaging.build_artifact(d)
    signer = signing.generate_keypair()
    other = signing.generate_keypair()
    sig = signing.sign(data, signer.private_key, key_id="s")
    with pytest.raises(VerificationError):
        evaluate(
            data, digest, Signature(**sig),
            policy="signed", root_key=None, trusted_keys=[TrustedKey("s", other.public_key, True)],
        )


def test_build_rejects_invalid_manifest(tmp_path):
    d = tmp_path / "bad"
    d.mkdir()
    # manifest_version 2 module with no trust_tier — invalid.
    (d / "plugin.yaml").write_text(
        "manifest_version: 2\nid: x\nname: X\nversion: 1.0.0\nkind: module\n"
    )
    with pytest.raises(packaging.PackagingError, match="trust_tier"):
        packaging.build_artifact(d)


def test_missing_manifest_rejected(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(packaging.PackagingError, match="plugin.yaml"):
        packaging.load_manifest(d)


def test_scaffold_pack_and_module_are_valid(tmp_path):
    theme = _theme_pack(tmp_path)
    assert packaging.load_manifest(theme).effective_kind.value == "pack"
    assert (theme / "payload" / "themes.json").exists()

    mod = tmp_path / "mod"
    scaffold.init_module(mod, module_id="you.mod", name="Mod", trust_tier="code")
    m = packaging.load_manifest(mod)
    assert m.effective_kind.value == "module" and m.trust_tier.value == "code"
    assert (mod / "__init__.py").exists()


def test_scaffold_refuses_nonempty(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    (d / "f").write_text("x")
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.init_pack(d, pack_id="a.b", name="B", pack_type="theme")


def test_cli_full_flow(tmp_path):
    src = tmp_path / "src"
    assert main(
        ["init", str(src), "--kind", "pack", "--pack-type", "theme", "--id", "you.t", "--name", "T"]
    ) == 0
    artifact = tmp_path / "out.fpmod"
    assert main(["build", str(src), "-o", str(artifact)]) == 0
    assert artifact.exists()

    kp = signing.generate_keypair()
    sig_path = tmp_path / "sig.json"
    assert main(["sign", str(artifact), "--key", kp.private_key, "--key-id", "k", "-o", str(sig_path)]) == 0
    sig = json.loads(sig_path.read_text())
    assert sig["algorithm"] == "ed25519" and sig["key_id"] == "k"

    assert main(["validate", str(artifact)]) == 0


def test_cli_build_bad_manifest_returns_1(tmp_path):
    d = tmp_path / "bad"
    d.mkdir()
    # kind: pack with no pack body — invalid regardless of manifest_version.
    (d / "plugin.yaml").write_text("id: x\nname: X\nversion: 1.0.0\nkind: pack\n")
    assert main(["build", str(d), "-o", str(tmp_path / "o.fpmod")]) == 1
