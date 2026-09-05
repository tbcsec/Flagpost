"""Module SDK — project scaffolding (#390, ADR-0040).

``init`` writes a minimal, *valid* skeleton so a new pack/module is born correct:
a manifest that passes ``ManifestModel`` validation and the right payload layout.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from utils.theme_tokens import THEME_TOKENS

_PAYLOAD_NOTE = {
    "challenges": "Add a ctfcli export (a zip of <slug>/challenge.yml folders) as payload/challenges.zip.",
    "automation-recipes": "Add automation recipe definitions under payload/.",
    "translations": "Translation packs are not installable yet (see docs/MODULES.md).",
}


class ScaffoldError(Exception):
    """The destination isn't a fresh directory to scaffold into."""


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _require_empty(dest: Path) -> None:
    if dest.exists() and any(dest.iterdir()):
        raise ScaffoldError(f"{dest} already exists and is not empty")


def init_pack(dest: Path, *, pack_id: str, name: str, pack_type: str) -> list[Path]:
    dest = Path(dest)
    _require_empty(dest)
    target = "site" if pack_type in ("theme", "translations") else "competition"
    manifest = {
        "manifest_version": 2,
        "id": pack_id,
        "name": name,
        "version": "0.1.0",
        "kind": "pack",
        "publisher": {"id": "you", "name": "Your name"},
        "pack": {"pack_type": pack_type, "target": target},
    }
    written = [dest / "plugin.yaml"]
    _write(written[0], yaml.safe_dump(manifest, sort_keys=False))
    if pack_type == "theme":
        preset = {
            "id": pack_id.replace(".", "-"),
            "name": name,
            "mode": "dark",
            "tokens": {token: "#1b2130" for token in THEME_TOKENS},
        }
        themes = dest / "payload" / "themes.json"
        _write(themes, json.dumps([preset], indent=2) + "\n")
        written.append(themes)
    else:
        note = dest / "payload" / "README.txt"
        _write(note, _PAYLOAD_NOTE.get(pack_type, "Add the pack payload here.") + "\n")
        written.append(note)
    return written


def init_module(dest: Path, *, module_id: str, name: str, trust_tier: str) -> list[Path]:
    dest = Path(dest)
    _require_empty(dest)
    manifest: dict = {
        "manifest_version": 2,
        "id": module_id,
        "name": name,
        "version": "0.1.0",
        "kind": "module",
        "trust_tier": trust_tier,
        "publisher": {"id": "you", "name": "Your name"},
        "requires_flagpost": {"min": "1.6.0"},
    }
    if trust_tier == "code":
        manifest["provides"] = {"routes": True}
    written = [dest / "plugin.yaml"]
    _write(written[0], yaml.safe_dump(manifest, sort_keys=False))
    if trust_tier == "code":
        stub = (
            f'"""{name} — a Flagpost module (#390, ADR-0040)."""\n\n\n'
            "def setup(app, event_bus, db_factory) -> None:\n"
            "    # Mount routers / subscribe event listeners here.\n"
            "    ...\n"
        )
        init_py = dest / "__init__.py"
        _write(init_py, stub)
        written.append(init_py)
    return written
