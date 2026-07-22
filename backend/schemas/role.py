"""Pydantic schemas for the roles admin API (ARCHITECTURE.md §7.4)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    is_system: bool
    scope: str
    permissions: list[str]


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=280)
    # Custom roles default to competition scope (§7.4).
    scope: Literal["global", "competition"] = "competition"
    permissions: list[str] = Field(default_factory=list)
    # When cloning, the source role's scope + permissions seed the new one
    # (any fields also passed in the body still win).
    clone_from: str | None = None


class RoleUpdate(BaseModel):
    # All optional — a PATCH. Scope is fixed at creation (assignments depend on
    # it), so it isn't editable here.
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=280)
    permissions: list[str] | None = None


class PermissionOut(BaseModel):
    """One catalog entry for the editor's permission matrix (§7.1)."""

    key: str
    category: str
    scope: str
    reserved: bool


class AssignmentCreate(BaseModel):
    # Assign by email so the roles admin doesn't need a full user directory.
    email: str = Field(min_length=1)
    role_id: str
    competition_id: str | None = None


class AssignmentOut(BaseModel):
    id: str
    user_id: str
    user_email: str
    user_display_name: str
    role_id: str
    role_name: str
    role_scope: str
    competition_id: str | None
    competition_name: str | None
