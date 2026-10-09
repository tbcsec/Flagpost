"""Module SDK command line (#390, ADR-0040). Run as ``python -m sdk``.

    python -m sdk keygen
    python -m sdk init ./my-pack --kind pack --pack-type theme --id you.my-theme
    python -m sdk build ./my-pack -o my-pack.fpmod
    python -m sdk sign my-pack.fpmod --key <private-b64> --key-id you:1 -o my-pack.sig.json
    python -m sdk validate ./my-pack        # or: validate my-pack.fpmod
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sdk import packaging, scaffold, signing
from utils.marketplace_verify import compute_digest


def _cmd_keygen(args: argparse.Namespace) -> int:
    kp = signing.generate_keypair()
    if args.json:
        print(json.dumps({"public_key": kp.public_key, "private_key": kp.private_key}))
    else:
        print(f"public_key:  {kp.public_key}")
        print(f"private_key: {kp.private_key}")
        print(
            "\nKeep the private key secret. Give the operator the public key to add "
            "to the marketplace trusted keys.",
            file=sys.stderr,
        )
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    try:
        data, digest = packaging.build_artifact(Path(args.src))
    except packaging.PackagingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    Path(args.out).write_bytes(data)
    print(f"built {args.out} ({len(data)} bytes)")
    print(f"digest: {digest}")
    return 0


def _cmd_sign(args: argparse.Namespace) -> int:
    try:
        data = Path(args.artifact).read_bytes()
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    sig = signing.sign(data, args.key, key_id=args.key_id)
    text = json.dumps(sig, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)
    print(f"digest: {compute_digest(data)}", file=sys.stderr)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.path)
    try:
        manifest = (
            packaging.load_manifest(path)
            if path.is_dir()
            else packaging.manifest_of_artifact(path.read_bytes())
        )
    except (packaging.PackagingError, OSError) as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    tier = f"/{manifest.trust_tier.value}" if manifest.trust_tier else ""
    print(f"ok: {manifest.id} v{manifest.version} ({manifest.effective_kind.value}{tier})")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    name = args.name or args.id
    try:
        if args.kind == "pack":
            written = scaffold.init_pack(
                Path(args.dest), pack_id=args.id, name=name, pack_type=args.pack_type
            )
        else:
            written = scaffold.init_module(
                Path(args.dest), module_id=args.id, name=name, trust_tier=args.trust_tier
            )
    except scaffold.ScaffoldError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for path in written:
        print(f"created {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sdk", description="Flagpost module SDK")
    sub = parser.add_subparsers(dest="command", required=True)

    keygen = sub.add_parser("keygen", help="generate an ed25519 signing keypair")
    keygen.add_argument("--json", action="store_true", help="emit JSON")
    keygen.set_defaults(func=_cmd_keygen)

    build = sub.add_parser("build", help="build a .fpmod artifact from a source dir")
    build.add_argument("src", help="source directory (contains plugin.yaml + payload/)")
    build.add_argument("-o", "--out", required=True, help="output .fpmod path")
    build.set_defaults(func=_cmd_build)

    sign = sub.add_parser("sign", help="sign a built artifact with a private key")
    sign.add_argument("artifact", help=".fpmod artifact to sign")
    sign.add_argument("--key", required=True, help="base64 ed25519 private key")
    sign.add_argument("--key-id", default="default", help="key id recorded in the signature")
    sign.add_argument("-o", "--out", help="write the signature JSON here (default: stdout)")
    sign.set_defaults(func=_cmd_sign)

    validate = sub.add_parser("validate", help="validate a source dir or a built artifact")
    validate.add_argument("path", help="source directory or .fpmod artifact")
    validate.set_defaults(func=_cmd_validate)

    init = sub.add_parser("init", help="scaffold a new pack or module")
    init.add_argument("dest", help="destination directory (must be empty)")
    init.add_argument("--kind", choices=["pack", "module"], default="pack")
    init.add_argument("--id", required=True, help="artifact id (e.g. you.my-pack)")
    init.add_argument("--name", default="", help="display name (defaults to the id)")
    init.add_argument(
        "--pack-type",
        choices=["challenges", "theme", "translations", "automation-recipes"],
        default="challenges",
    )
    init.add_argument("--trust-tier", choices=["declarative", "code"], default="code")
    init.set_defaults(func=_cmd_init)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))
