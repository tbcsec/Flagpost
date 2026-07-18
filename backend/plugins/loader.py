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
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger("module_loader")

PLUGINS_DIR = Path(__file__).resolve().parent


class ModuleError(Exception):
    """A module manifest is malformed, or its dependency graph is unsatisfiable."""


@dataclass
class ModuleManifest:
    id: str
    name: str
    version: str
    required_core: bool = False
    provides_routes: bool = False
    provides_event_listeners: bool = False
    dependencies: list[str] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        # Required-core modules are never disableable (§11.3). Optional modules
        # will read persisted admin state here once disabling exists; until then
        # everything in the box is on.
        return True


def parse_manifest(data: dict, *, source: str = "<dict>") -> ModuleManifest:
    """Build a manifest from parsed YAML, validating required fields."""
    try:
        provides = data.get("provides") or {}
        return ModuleManifest(
            id=data["id"],
            name=data["name"],
            version=str(data["version"]),
            required_core=bool(data.get("required_core", False)),
            provides_routes=bool(provides.get("routes", False)),
            provides_event_listeners=bool(provides.get("event_listeners", False)),
            dependencies=list(data.get("dependencies") or []),
        )
    except KeyError as exc:
        raise ModuleError(f"{source}: manifest missing required field {exc}") from exc


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
        logger.info(
            "loaded module %s v%s%s",
            manifest.id,
            manifest.version,
            " (required-core)" if manifest.required_core else "",
        )
    return order
