"""Pydantic schemas for custom brand themes (#323, ADR-0011).

The token map + mode are format-validated here (``utils.theme_tokens``); the id
is a slug that must not shadow a built-in palette. The server validates shape
and never interprets — the same posture as ``default_palette`` / ``accent``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from utils.theme_tokens import (
    RESERVED_PALETTE_IDS,
    validate_theme_mode,
    validate_theme_tokens,
)

# A theme id is a lowercase slug — same grammar as site_settings.PALETTE_PATTERN
# (kept local so site_settings can import ThemePublic from here without a cycle).
THEME_ID_PATTERN = r"^[a-z][a-z0-9-]{1,31}$"


class ThemeOut(BaseModel):
    """A theme as the admin manager sees it."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    mode: str
    tokens: dict
    source: str
    created_at: datetime


class ThemePublic(BaseModel):
    """The active theme embedded in the public site-settings payload — the
    minimum the runtime paint needs, no authorship/labels."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    mode: str
    tokens: dict


class ThemeCreate(BaseModel):
    id: str = Field(pattern=THEME_ID_PATTERN, description="Immutable slug id")
    name: str = Field(min_length=1, max_length=60)
    mode: str
    tokens: dict

    @field_validator("id")
    @classmethod
    def _id_not_reserved(cls, v: str) -> str:
        if v in RESERVED_PALETTE_IDS:
            raise ValueError(f"'{v}' is a built-in palette id — choose another")
        return v

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, v: str) -> str:
        return validate_theme_mode(v)

    @field_validator("tokens")
    @classmethod
    def _validate_tokens(cls, v: object) -> dict:
        return validate_theme_tokens(v)


class ThemeUpdate(BaseModel):
    """Partial update. The id is immutable (it's the active-theme pointer), so it
    isn't updatable; a provided token map must still be complete + valid."""

    name: str | None = Field(default=None, min_length=1, max_length=60)
    mode: str | None = None
    tokens: dict | None = None

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, v: str | None) -> str | None:
        return None if v is None else validate_theme_mode(v)

    @field_validator("tokens")
    @classmethod
    def _validate_tokens(cls, v: object | None) -> dict | None:
        return None if v is None else validate_theme_tokens(v)
