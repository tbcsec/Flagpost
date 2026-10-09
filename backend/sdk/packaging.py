"""Module SDK — artifact packaging + validation (#390, ADR-0040).

Build a ``.fpmod`` (a zip of ``plugin.yaml`` + ``payload/…``) from a source
directory, validating its manifest through the same ``plugins.manifest.ManifestModel``
the loader uses, and compute its ``sha256:`` digest — the content address the
registry publishes and the instance pins.

The build is **deterministic**: entries are sorted, the mtime is fixed, and file
modes are normalised, so the same source always yields the same bytes (and the
same digest). That is what lets a publisher and an instance agree on an artifact's
identity independently.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import yaml
from pydantic import ValidationError

from plugins.manifest import ManifestModel
from utils.marketplace_verify import compute_digest

# A fixed DOS timestamp so the archive bytes don't depend on the file mtimes.
_FIXED_DATE = (1980, 1, 1, 0, 0, 0)


class PackagingError(Exception):
    """A source tree can't be packaged — missing/invalid manifest, or bad layout."""


def load_manifest(src_dir: Path) -> ManifestModel:
    """Validate ``src_dir/plugin.yaml`` through the manifest-v2 model."""
    src_dir = Path(src_dir)
    manifest_path = src_dir / "plugin.yaml"
    if not manifest_path.exists():
        raise PackagingError(f"{src_dir}: missing plugin.yaml")
    try:
        data = yaml.safe_load(manifest_path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise PackagingError(f"plugin.yaml is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PackagingError("plugin.yaml is not a mapping")
    try:
        return ManifestModel.model_validate(data)
    except ValidationError as exc:
        raise PackagingError(f"invalid manifest: {exc}") from exc


def build_artifact(src_dir: Path) -> tuple[bytes, str]:
    """Validate the manifest, then deterministically zip ``src_dir`` into artifact
    bytes. Returns ``(bytes, digest)``."""
    src_dir = Path(src_dir)
    load_manifest(src_dir)  # fail before packaging if the manifest is bad

    files = sorted(
        (p for p in src_dir.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(src_dir).as_posix(),
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arcname = path.relative_to(src_dir).as_posix()
            info = zipfile.ZipInfo(arcname, date_time=_FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16  # -rw-r--r--
            zf.writestr(info, path.read_bytes())
    data = buf.getvalue()
    return data, compute_digest(data)


def manifest_of_artifact(artifact_bytes: bytes) -> ManifestModel:
    """Read + validate the manifest inside a built ``.fpmod`` artifact."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(artifact_bytes))
    except zipfile.BadZipFile as exc:
        raise PackagingError("not a valid artifact (bad zip)") from exc
    try:
        raw = zf.read("plugin.yaml")
    except KeyError as exc:
        raise PackagingError("artifact is missing plugin.yaml") from exc
    try:
        return ManifestModel.model_validate(yaml.safe_load(raw) or {})
    except ValidationError as exc:
        raise PackagingError(f"invalid manifest: {exc}") from exc
