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


class ModuleToggle(BaseModel):
    enabled: bool
