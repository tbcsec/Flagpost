"""Content-pack import — Tier 0 of the module marketplace (ADR-0040, docs/MODULES.md §1).

A **content pack** is a ``kind: pack`` artifact: *data, no executable code*. It
installs an existing content type through that type's **existing importer, with
that importer's existing validation** — the whole point of Tier 0 is that it
carries no new trust surface. This module unpacks a pack, validates its manifest
through the manifest-v2 model (``plugins/manifest.py``), and dispatches to the
right importer.

**Validation is never bypassed.** Each type re-runs the same boundary its
authoring route enforces — the lesson from backup import (#323/#324), where
loading a row straight into the ORM skipped the route validators. Theme presets
go through the ``ThemeCreate`` schema; challenges through ``import_challenges``
(which validates deployment specs + hashes flags itself).

**Pack layout** (a zip):

    plugin.yaml              # the manifest, kind: pack
    payload/
        challenges.zip       # (pack_type: challenges) a ctfcli export zip
        themes.json          # (pack_type: theme) a JSON array of theme presets

v1 supports ``challenges`` (into a competition) and ``theme`` (site-wide). The
other declared pack types raise a clear "not supported yet" error: translations
have no backend store today, and automation recipes need an import-time validator
first (both tracked as follow-ups on #387).
"""

from __future__ import annotations

import io
import json
import re
import zipfile

import yaml
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models.competition import Competition
from models.theme_preset import ThemePreset
from plugins.manifest import Kind, ManifestModel, PackType
from schemas.theme import ThemeCreate
from storage.base import ObjectStorage
from utils.challenge_yaml import import_challenges

# A pack's declared uncompressed size is capped so a malformed or hostile archive
# can't exhaust memory/disk on unpack. Generous enough for real challenge packs
# with attachments; the route also bounds the upload itself.
MAX_PACK_UNCOMPRESSED = 200 * 1024 * 1024  # 200 MiB

_THEMES_MEMBER = "payload/themes.json"
_CHALLENGES_MEMBER = "payload/challenges.zip"


class PackError(ValueError):
    """A content pack is malformed, incompatible, or unsupported. The route maps
    it to a 400 with the message."""


def _version_tuple(v: str) -> tuple[int, int, int]:
    """Parse ``1.7.0`` / ``1.6.0-src`` → ``(1, 6, 0)`` (leading ints per part,
    pre-release/build suffixes ignored). Lenient by design — compatibility is a
    coarse guard, not a semver engine."""
    parts: list[int] = []
    for piece in str(v).split(".")[:3]:
        m = re.match(r"\d+", piece)
        parts.append(int(m.group()) if m else 0)
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def _open_pack(pack_bytes: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(pack_bytes))
    except zipfile.BadZipFile as exc:
        raise PackError("not a valid pack archive (bad zip)") from exc
    declared = sum(info.file_size for info in zf.infolist())
    if declared > MAX_PACK_UNCOMPRESSED:
        raise PackError("pack is too large")
    return zf


def _manifest_from_zip(zf: zipfile.ZipFile) -> ManifestModel:
    try:
        raw = zf.read("plugin.yaml")
    except KeyError as exc:
        raise PackError("pack is missing plugin.yaml") from exc
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise PackError(f"pack manifest is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PackError("pack manifest is not a mapping")
    try:
        manifest = ManifestModel.model_validate(data)
    except ValidationError as exc:
        raise PackError(f"invalid pack manifest: {exc}") from exc
    if manifest.effective_kind != Kind.pack:
        raise PackError("not a content pack (manifest 'kind' must be 'pack')")
    return manifest


def read_pack_manifest(pack_bytes: bytes) -> ManifestModel:
    """Validate + return a pack's manifest without applying it. Used by the
    install-confirmation path (#389) and by ``apply_pack``."""
    return _manifest_from_zip(_open_pack(pack_bytes))


def _check_compat(manifest: ManifestModel) -> None:
    req = manifest.requires_flagpost
    if req is None:
        return
    current = _version_tuple(config.SOURCE_BUILD_VERSION)
    if _version_tuple(req.min) > current:
        raise PackError(f"pack requires Flagpost >= {req.min}")
    if req.max is not None and _version_tuple(req.max) <= current:
        raise PackError(f"pack requires Flagpost < {req.max}")


def _read_member(zf: zipfile.ZipFile, name: str) -> bytes:
    try:
        return zf.read(name)
    except KeyError as exc:
        raise PackError(f"pack is missing {name}") from exc


async def _apply_theme_pack(
    zf: zipfile.ZipFile, db: AsyncSession, actor_user_id: str | None
) -> dict:
    """Install theme presets site-wide. Additive (an existing id is skipped);
    atomic (every preset is validated through ``ThemeCreate`` before any insert,
    so one bad preset installs none)."""
    try:
        presets = json.loads(_read_member(zf, _THEMES_MEMBER))
    except json.JSONDecodeError as exc:
        raise PackError(f"{_THEMES_MEMBER} is not valid JSON: {exc}") from exc
    if not isinstance(presets, list):
        raise PackError(f"{_THEMES_MEMBER} must be a JSON array of theme presets")

    validated: list[ThemeCreate] = []
    for i, preset in enumerate(presets):
        if not isinstance(preset, dict):
            raise PackError(f"theme #{i} is not an object")
        try:
            validated.append(ThemeCreate.model_validate(preset))
        except ValidationError as exc:
            raise PackError(f"theme {preset.get('id')!r}: {exc}") from exc

    installed = 0
    skipped = 0
    for tc in validated:
        if await db.get(ThemePreset, tc.id) is not None:
            skipped += 1
            continue
        db.add(
            ThemePreset(
                id=tc.id,
                name=tc.name,
                mode=tc.mode,
                tokens=tc.tokens,
                source="custom",
                created_by=actor_user_id,
            )
        )
        installed += 1
    await db.commit()
    return {"installed": installed, "skipped": skipped}


async def apply_pack(
    db: AsyncSession,
    storage: ObjectStorage,
    pack_bytes: bytes,
    *,
    competition: Competition | None = None,
    actor_user_id: str | None = None,
) -> dict:
    """Validate + install a content pack. Returns a summary of what was applied.

    Atomic per pack (a pack carries exactly one content type). Commits on success;
    the caller emits the single ``platform.content_pack_installed`` event
    afterward (commit-then-emit; bulk import emits no per-row events).
    """
    zf = _open_pack(pack_bytes)
    manifest = _manifest_from_zip(zf)
    _check_compat(manifest)
    pack_type = manifest.pack.pack_type  # guaranteed present when kind == pack

    if pack_type == PackType.challenges:
        if competition is None:
            raise PackError("a challenge pack must target a competition")
        result = await import_challenges(
            db, competition, _read_member(zf, _CHALLENGES_MEMBER), storage
        )
        target = competition.id
    elif pack_type == PackType.theme:
        result = await _apply_theme_pack(zf, db, actor_user_id)
        target = "site"
    else:
        raise PackError(
            f"pack type {pack_type.value!r} is not supported yet"
        )

    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "pack_type": pack_type.value,
        "target": target,
        "result": result,
    }
