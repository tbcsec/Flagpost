"""Schemas for the AI module's site-level provider config (#98, ADR-0023).

The ``api_key`` is **write-only**, exactly like the SMTP password and the
identity-provider secrets: a read exposes only ``api_key_set`` (whether one is
stored), and an update omitting the field leaves the stored key untouched while
``""`` clears it (a keyless local endpoint).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GuidanceLevel = Literal["platform_only", "conceptual", "guided"]


class AiSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    enabled: bool
    base_url: str | None
    model: str | None
    max_output_tokens: int
    competitor_max_output_tokens: int
    request_timeout_s: int
    admin_prompt_override: str | None
    competitor_prompt_override: str | None
    default_guidance_level: str
    # Write-only: only whether a key is stored is ever returned.
    api_key_set: bool = False
    updated_at: datetime | None = None


class AiSettingsUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=1000)
    model: str | None = Field(default=None, max_length=200)
    # None leaves the stored key untouched; "" clears it (keyless local endpoint).
    api_key: str | None = Field(default=None, max_length=4000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=32000)
    competitor_max_output_tokens: int | None = Field(default=None, ge=1, le=32000)
    request_timeout_s: int | None = Field(default=None, ge=1, le=600)
    admin_prompt_override: str | None = Field(default=None, max_length=20000)
    competitor_prompt_override: str | None = Field(default=None, max_length=20000)
    default_guidance_level: GuidanceLevel | None = None


class TestConnectionCheck(BaseModel):
    """One leg of the connection test, reported on its own so an operator can see
    (for example) that completions work but tool-calling doesn't — the common
    small-local-model gap the assistants can't tolerate."""

    ok: bool
    detail: str


class TestConnectionResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    completion: TestConnectionCheck
    tool_call: TestConnectionCheck
    model: str
