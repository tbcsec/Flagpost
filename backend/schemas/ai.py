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


# --- per-competition controls (Phase 3) -------------------------------------


class AiCompetitionSettingsOut(BaseModel):
    """The competitor-assistant controls for one competition (organiser view).
    ``guidance_level`` is the raw override (null = inherit);
    ``effective_guidance_level`` is what actually applies after inheritance, so
    the UI can show "inheriting: conceptual" without re-deriving it."""

    model_config = ConfigDict(from_attributes=True)

    competitor_enabled: bool
    guidance_level: str | None
    effective_guidance_level: str
    challenge_metadata_access: bool
    updated_at: datetime | None = None


class AiCompetitionSettingsUpdate(BaseModel):
    # guidance_level: omit to leave unchanged; null clears the override (inherit
    # the site default); a level sets an override. The router reads
    # ``model_fields_set`` to tell "omitted" from an explicit null.
    competitor_enabled: bool | None = None
    guidance_level: GuidanceLevel | None = None
    challenge_metadata_access: bool | None = None


# --- conversations (Phase 2) -------------------------------------------------


AssistantType = Literal["admin", "competitor"]


class AiConversationCreate(BaseModel):
    assistant_type: AssistantType = "admin"


class AiConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    assistant_type: str
    created_at: datetime
    closed_at: datetime | None = None


class AiMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    # Names of the tools the assistant turn invoked (metadata, no content).
    tool_calls: list | None = None
    created_at: datetime


class AiConversationDetail(AiConversationOut):
    messages: list[AiMessageOut]


class AiMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class AiUsageOut(BaseModel):
    input_tokens: int
    output_tokens: int
    message_count: int


class AiAvailabilityOut(BaseModel):
    """Which assistant(s) the caller can open in this competition right now — the
    audience-aware launcher gate. Both false when the module is off/unconfigured.
    ``admin`` is true for staff who hold a tool permission; ``competitor`` is true
    for a participant when the competition is running and its competitor assistant
    is enabled. Neither exposes provider config to a non-``manage_ai`` caller."""

    admin: bool = False
    competitor: bool = False
    # Whether the caller has accepted the competitor-assistant disclosure (only
    # meaningful when ``competitor`` is true) — drives the first-run modal.
    competitor_disclosure_accepted: bool = False


class AiTranscriptSummary(BaseModel):
    """One competitor conversation in the organiser's transcript-review list."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    user_display_name: str
    assistant_type: str
    message_count: int
    created_at: datetime
    # When the thread was last active (its newest message) — the useful sort key
    # and "last seen" for a long-lived, resumed conversation, distinct from when
    # it was first opened (``created_at``).
    last_activity_at: datetime
    closed_at: datetime | None = None


class AiTranscriptDetail(AiTranscriptSummary):
    messages: list[AiMessageOut] = []
