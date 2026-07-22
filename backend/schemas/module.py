"""Pydantic schemas for per-competition module state (ARCHITECTURE.md §11.3)."""

from pydantic import BaseModel


class ModuleStateOut(BaseModel):
    id: str
    name: str
    version: str
    enabled: bool


class ModuleToggle(BaseModel):
    enabled: bool
