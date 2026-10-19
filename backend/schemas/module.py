"""Pydantic schemas for per-competition module state (ARCHITECTURE.md §11.3)."""

from pydantic import BaseModel


class ModuleStateOut(BaseModel):
    id: str
    name: str
    version: str
    enabled: bool
    # Required-core modules are part of the platform floor (§11.3): always on,
    # never toggleable. The admin inventory lists them locked alongside the
    # optional (per-competition toggleable) ones.
    required_core: bool
    # The manifest's one-liner — developer-facing; the UI writes its own copy
    # per module and falls back to this for one it doesn't know (#502).
    description: str = ""
    # An inert module (ai, instances, judge) whose site-wide switch is off:
    # enabling it here does nothing until an administrator sets it up (#502).
    needs_setup: bool = False


class ModuleToggle(BaseModel):
    enabled: bool


class ModuleCatalogEntry(BaseModel):
    """A site-level catalog entry for an optional module — enough to render the
    at-creation module picker (#252) before any competition exists: id, display
    name, and a one-line description. Per-competition enabled state is a
    separate read."""

    id: str
    name: str
    description: str
    needs_setup: bool = False


class ModulesInUseOut(BaseModel):
    """Which inert modules are of use in a competition (#511): switched on
    site-wide, or already holding this competition's data. The sidebar shows
    their entries only then. A module the caller may not view reads false."""

    ai: bool = False
    instances: bool = False
