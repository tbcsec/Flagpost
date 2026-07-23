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

from utils.event_catalog import is_triggerable

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
    # http(s) only; the per-call SSRF check + header stripping happen at send
    # time (utils/webhook_security.py, §5.4) — this is just the cheap up-front
    # scheme guard so an obviously-bad URL is rejected at rule save too.
    url: str = Field(pattern=r"^https?://", max_length=2000)
    headers: dict[str, str] | None = None
    # With a body_template, competitor-controlled {field} values are escaped +
    # defanged for this content type (§5.4). Without one, the structured event
    # is sent as JSON to a generic endpoint.
    content_type: Literal[
        "application/json",
        "application/x-www-form-urlencoded",
        "text/plain",
    ] = "application/json"
    body_template: str | None = Field(default=None, max_length=_TEMPLATE_MAX)


class ReleaseHintAction(BaseModel):
    type: Literal["release_hint"]
    hint_id: str = Field(min_length=1)


class UnlockChallengeAction(BaseModel):
    type: Literal["unlock_challenge"]
    challenge_id: str = Field(min_length=1)


class OpenSurveyAction(BaseModel):
    type: Literal["open_survey"]
    survey_id: str = Field(min_length=1)


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


class CreateAwardAction(BaseModel):
    type: Literal["create_award"]
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=_TEMPLATE_MAX)
    # Points the award grants; bounded like update_score so a typo can't hand
    # out a fortune per trigger. 0 = a pure badge.
    points: int = Field(default=0, ge=-10000, le=10000)


class FreezeScoreboardAction(BaseModel):
    type: Literal["freeze_scoreboard"]


class UnfreezeScoreboardAction(BaseModel):
    type: Literal["unfreeze_scoreboard"]


class CreateAnnouncementAction(BaseModel):
    type: Literal["create_announcement"]
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=_TEMPLATE_MAX)


Action = Annotated[
    Union[
        NotifyAction,
        SendEmailAction,
        WebhookAction,
        ReleaseHintAction,
        UnlockChallengeAction,
        OpenSurveyAction,
        CreateTicketAction,
        UpdateScoreAction,
        CreateAwardAction,
        FreezeScoreboardAction,
        UnfreezeScoreboardAction,
        CreateAnnouncementAction,
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


class CatalogField(BaseModel):
    """One config input the builder renders for an action (§5.5)."""

    key: str
    label: str
    kind: Literal["text", "textarea", "number", "select", "string_list", "keyvalue"]
    required: bool = True
    options: list[str] | None = None
    placeholder: str | None = None
    # Supports {field} interpolation from the event payload — a UI hint.
    templateable: bool = False


class TriggerEntry(BaseModel):
    event: str
    label: str
    # Payload fields available for conditions / {placeholders}.
    fields: list[str]


class OperatorEntry(BaseModel):
    value: str
    label: str
    # exists / not_exists take no value input.
    unary: bool


class ActionCatalogEntry(BaseModel):
    type: str
    label: str
    personal_allowed: bool
    fields: list[CatalogField]


class AutomationCatalog(BaseModel):
    """Everything the rule editor is generated from (§5.5): triggers with their
    payload fields, condition operators, and action types with their config
    fields. Built by ``utils.automation_catalog.build_catalog``."""

    triggers: list[TriggerEntry]
    operators: list[OperatorEntry]
    actions: list[ActionCatalogEntry]
