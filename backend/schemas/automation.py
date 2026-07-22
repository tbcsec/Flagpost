"""Pydantic schemas for automation rules (ARCHITECTURE.md §5.1, §5.3).

Rule payloads are validated **here, at write time** — the engine treats stored
``conditions``/``actions`` as data and reads them defensively, so this layer is
what keeps a rule row well-formed: ``trigger_type`` must be a triggerable §3.2
event (utils/event_catalog.py), every condition operator must be one the engine
implements, and each action's config is checked by a per-type model. Personal
rules (§5.1) are validated stricter: only ``notify`` with ``target="self"``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, field_validator

from utils.automation_engine import CONDITION_OPERATORS
from utils.event_catalog import TRIGGERABLE_EVENTS, is_triggerable

_TEMPLATE_MAX = 2000


class Condition(BaseModel):
    field: str = Field(min_length=1, max_length=100)
    operator: Literal[
        "equals",
        "not_equals",
        "contains",
        "gt",
        "gte",
        "lt",
        "lte",
        "exists",
        "not_exists",
    ]
    value: str | int | float | bool | None = None


# One config model per §5.3 action type. ``type`` is the discriminator the
# engine's registry dispatches on; everything else is that executor's config.


class NotifyAction(BaseModel):
    type: Literal["notify"]
    target: Literal["event_user", "event_team", "role", "self"]
    role_name: str | None = Field(default=None, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=_TEMPLATE_MAX)

    @field_validator("role_name")
    @classmethod
    def _role_needs_name(cls, v, info):
        if info.data.get("target") == "role" and not v:
            raise ValueError("target 'role' requires role_name")
        return v


class SendEmailAction(BaseModel):
    type: Literal["send_email"]
    to: list[str] = Field(min_length=1, max_length=20)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=_TEMPLATE_MAX)


class WebhookAction(BaseModel):
    type: Literal["webhook"]
    # http(s) only — the fuller §5.4 SSRF/header hardening is the next phase.
    url: str = Field(pattern=r"^https?://", max_length=2000)
    headers: dict[str, str] | None = None


class ReleaseHintAction(BaseModel):
    type: Literal["release_hint"]
    hint_id: str = Field(min_length=1)


class UnlockChallengeAction(BaseModel):
    type: Literal["unlock_challenge"]
    challenge_id: str = Field(min_length=1)


class CreateTicketAction(BaseModel):
    type: Literal["create_ticket"]
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=_TEMPLATE_MAX)


class UpdateScoreAction(BaseModel):
    type: Literal["update_score"]
    # Signed: positive bonus, negative penalty. Bounded so a typo'd rule can't
    # hand out a million points per trigger.
    points: int = Field(ge=-10000, le=10000)
    reason: str = Field(min_length=1, max_length=200)


class AwardAchievementAction(BaseModel):
    type: Literal["award_achievement"]
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=_TEMPLATE_MAX)


Action = Annotated[
    Union[
        NotifyAction,
        SendEmailAction,
        WebhookAction,
        ReleaseHintAction,
        UnlockChallengeAction,
        CreateTicketAction,
        UpdateScoreAction,
        AwardAchievementAction,
    ],
    Field(discriminator="type"),
]


class _RuleBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    trigger_type: str
    conditions: list[Condition] = Field(default_factory=list, max_length=20)
    actions: list[Action] = Field(min_length=1, max_length=10)
    is_enabled: bool = True

    @field_validator("trigger_type")
    @classmethod
    def _known_trigger(cls, v: str) -> str:
        if not is_triggerable(v):
            raise ValueError(
                f"unknown or non-triggerable event type {v!r} (see the catalog)"
            )
        return v


class RuleCreate(_RuleBase):
    """An org rule (§5.1). Competition scope comes from the request context
    (?competition_id=…), not the body — the same place the permission check
    reads it (§7.6)."""


class RuleUpdate(_RuleBase):
    pass


class PersonalRuleCreate(_RuleBase):
    """A personal rule (§5.1): notify-self only, optional competition scope."""

    competition_id: str | None = None

    @field_validator("actions")
    @classmethod
    def _notify_self_only(cls, actions: list[Action]) -> list[Action]:
        for action in actions:
            if action.type != "notify" or action.target != "self":
                raise ValueError(
                    "personal rules may only use the notify action targeting self"
                )
        return actions


class RuleOut(BaseModel):
    id: str
    name: str
    trigger_type: str
    conditions: list[Condition]
    actions: list[dict]
    is_enabled: bool
    competition_id: str | None
    owner_user_id: str | None
    trigger_count: int
    last_triggered_at: datetime | None
    created_at: datetime


class ActionCatalogEntry(BaseModel):
    type: str
    personal_allowed: bool


class AutomationCatalog(BaseModel):
    """What the rule editor needs to offer: triggers, operators, action types.
    (Phase 3's builder enriches this with payload field hints.)"""

    triggers: list[str] = Field(default_factory=lambda: list(TRIGGERABLE_EVENTS))
    operators: list[str] = Field(
        default_factory=lambda: list(CONDITION_OPERATORS)
    )
    actions: list[ActionCatalogEntry]
