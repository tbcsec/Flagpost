"""Manifest-driven module loader (ARCHITECTURE.md §11.1, ADR-0002).

Every backend feature above the kernel registers through this one path —
required-core (Challenges, Scoring, …) and, later, optional/marketplace
modules alike (§11.3). A module is a package under ``backend/plugins/<id>/``
with:

- a ``plugin.yaml`` manifest declaring what it provides, and
- a ``setup(app, event_bus, db_factory)`` entry point that does the actual
  wiring (mounts its router, registers event listeners).

Tier 1 scope: discovery, dependency resolution, and mounting for the in-box
required-core modules. Deferred until an *optional* module actually ships
(nothing in Tier 1 is toggleable, §11.3): the per-request ``enabled`` gate
(§11.1 step 3), plugin settings, widgets, nav items, and the frontend
extension slots (§11.2). The manifest already carries the shape so those are
additive, not a retrofit. The dependency machinery is built now because it's
pure logic that's cheap to get right early and awkward to bolt on later.

Licensing: Flagpost is licensed under the Apache License 2.0 (``LICENSE`` in
the repository root), so third-party modules loaded through this mechanism may
carry any license — no exception instrument is needed. Releases up to v1.5.0
were AGPL-3.0 with the Flagpost Module Exception granting this same freedom;
the v1.5.1 relicense (ADR-0035) retired it.
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from plugins.manifest import ManifestModel

logger = logging.getLogger("module_loader")

PLUGINS_DIR = Path(__file__).resolve().parent


class ModuleError(Exception):
    """A module manifest is malformed, or its dependency graph is unsatisfiable."""


@dataclass
class ModuleManifest:
    id: str
    name: str
    version: str
    # One-line, human-facing summary of what the module does. Optional in the
    # manifest; surfaced by the at-creation module picker (#252). Empty for
    # modules that don't set it (required-core ones aren't offered there).
    description: str = ""
    required_core: bool = False
    provides_routes: bool = False
    provides_event_listeners: bool = False
    dependencies: list[str] = field(default_factory=list)
    # Manifest v2 (ADR-0040, plugins/manifest.py). Legacy in-box manifests are
    # v1 and omit these: kind defaults to "module" and trust_tier stays None
    # (first-party kernel-trusted code). A registry-distributed module carries
    # both, plus the capabilities it requested for the install-consent screen.
    kind: str = "module"
    trust_tier: str | None = None
    capabilities: list[str] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        # Whether the module is loaded/mounted at all (site level). Required-core
        # modules are never disableable (§11.3); optional in-box modules always
        # *load* too — their per-competition disable (§11.3) is runtime state
        # checked by ``is_module_enabled``, not a reason to skip mounting.
        return True


def _summarize_validation_error(exc: ValidationError) -> str:
    """Flatten a Pydantic error into a one-line ``field: message; …`` summary."""
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(manifest)"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


def parse_manifest(data: dict, *, source: str = "<dict>") -> ModuleManifest:
    """Validate a parsed ``plugin.yaml`` (manifest v2, ADR-0040) into the loader's
    runtime :class:`ModuleManifest`.

    Fails closed: a malformed manifest raises :class:`ModuleError` with a concise,
    source-prefixed message rather than loading a half-formed module. In-box v1
    manifests (no ``manifest_version``/``kind``/``trust_tier``) validate leniently
    as first-party code — see ``plugins/manifest.py`` and
    ``docs/spec/module-manifest.schema.json``.
    """
    if not isinstance(data, dict):
        raise ModuleError(f"{source}: manifest is not a mapping")
    try:
        model = ManifestModel.model_validate(data)
    except ValidationError as exc:
        raise ModuleError(
            f"{source}: invalid manifest: {_summarize_validation_error(exc)}"
        ) from exc
    return ModuleManifest(
        id=model.id,
        name=model.name,
        version=model.version,
        description=model.description,
        required_core=model.required_core,
        provides_routes=model.provides.routes,
        provides_event_listeners=model.provides.event_listeners,
        dependencies=list(model.dependencies),
        kind=model.effective_kind.value,
        trust_tier=model.trust_tier.value if model.trust_tier else None,
        capabilities=[c.value for c in model.capabilities],
    )


def resolve_load_order(manifests: list[ModuleManifest]) -> list[ModuleManifest]:
    """Topologically order modules so each loads after its dependencies.

    Raises ``ModuleError`` on a missing dependency, a dependency that is present
    but disabled (§11.3 — the loader refuses to enable a module whose
    dependency isn't active, rather than leaving a competition half-configured),
    a duplicate id, or a dependency cycle.
    """
    by_id: dict[str, ModuleManifest] = {}
    for m in manifests:
        if m.id in by_id:
            raise ModuleError(f"duplicate module id {m.id!r}")
        by_id[m.id] = m

    for m in manifests:
        for dep in m.dependencies:
            if dep not in by_id:
                raise ModuleError(f"module {m.id!r} depends on missing module {dep!r}")
            if not by_id[dep].enabled:
                raise ModuleError(
                    f"module {m.id!r} depends on disabled module {dep!r}"
                )

    ordered: list[ModuleManifest] = []
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(m: ModuleManifest) -> None:
        if m.id in done:
            return
        if m.id in visiting:
            raise ModuleError(f"dependency cycle involving module {m.id!r}")
        visiting.add(m.id)
        for dep in m.dependencies:
            visit(by_id[dep])
        visiting.discard(m.id)
        done.add(m.id)
        ordered.append(m)

    for m in manifests:
        visit(m)
    return ordered


def discover_manifests(plugins_dir: Path = PLUGINS_DIR) -> list[ModuleManifest]:
    """Scan ``plugins_dir`` for subdirectories containing a ``plugin.yaml``."""
    manifests: list[ModuleManifest] = []
    for entry in sorted(plugins_dir.iterdir()):
        manifest_path = entry / "plugin.yaml"
        if not entry.is_dir() or not manifest_path.exists():
            continue
        data = yaml.safe_load(manifest_path.read_text()) or {}
        manifests.append(parse_manifest(data, source=str(manifest_path)))
    return manifests


# Manifests of the modules actually loaded this process, by id — populated by
# load_modules so runtime checks (is_module_enabled, the module-state admin
# surface) can reason about what exists without re-scanning the directory.
_loaded_manifests: dict[str, ModuleManifest] = {}


def load_modules(app, event_bus, db_factory, plugins_dir: Path = PLUGINS_DIR) -> list[ModuleManifest]:
    """Discover, order, and wire every enabled module. Returns the load order."""
    manifests = [m for m in discover_manifests(plugins_dir) if m.enabled]
    order = resolve_load_order(manifests)
    for manifest in order:
        module = importlib.import_module(f"plugins.{manifest.id}")
        setup = getattr(module, "setup", None)
        if not callable(setup):
            raise ModuleError(f"module {manifest.id!r} has no setup() entry point")
        setup(app, event_bus, db_factory)
        _loaded_manifests[manifest.id] = manifest
        logger.info(
            "loaded module %s v%s%s",
            manifest.id,
            manifest.version,
            " (required-core)" if manifest.required_core else "",
        )
    return order


def loaded_manifest(module_id: str) -> ModuleManifest | None:
    return _loaded_manifests.get(module_id)


def optional_modules() -> list[ModuleManifest]:
    """The loaded modules that carry a per-competition toggle (§11.3)."""
    return [m for m in _loaded_manifests.values() if not m.required_core]


def all_manifests() -> list[ModuleManifest]:
    """Every loaded module manifest (core + optional) — the admin inventory."""
    return list(_loaded_manifests.values())


async def is_module_enabled(db, module_id: str, competition_id: str | None) -> bool:
    """Is ``module_id`` active in ``competition_id``'s context? (§11.3, §11.1.3)

    Required-core modules are always on. An optional module defaults to
    **enabled** — a ``competition_modules`` row exists only to override that.
    ``competition_id=None`` (a global/site-wide context) has no per-competition
    toggle to consult, so a loaded module counts as enabled there. An id that
    isn't a loaded module at all is never "enabled".
    """
    manifest = _loaded_manifests.get(module_id)
    if manifest is None:
        return False
    if manifest.required_core or competition_id is None:
        return True

    from sqlalchemy import select

    from models.competition_module import CompetitionModule

    state = await db.scalar(
        select(CompetitionModule.enabled).where(
            CompetitionModule.competition_id == competition_id,
            CompetitionModule.module_id == module_id,
        )
    )
    return True if state is None else bool(state)
