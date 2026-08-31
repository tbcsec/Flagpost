"""Pydantic schemas for announcements (ROADMAP #14, #40)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.announcement import DEFAULT_AUDIENCE, DEFAULT_SEVERITY

Severity = Literal["info", "warning", "critical"]
AudienceType = Literal["all", "teams", "users"]


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    severity: Severity = DEFAULT_SEVERITY
    audience_type: AudienceType = DEFAULT_AUDIENCE
    # Team ids or user ids, per audience_type. Cleared for "all".
    audience_ids: list[str] = Field(default_factory=list, max_length=500)
    # Optional scheduled publish time (#349). A future time makes this a
    # staff-only draft until the scheduler releases it; null/past = post now.
    publish_at: datetime | None = None

    @model_validator(mode="after")
    def _check_audience(self) -> "AnnouncementCreate":
        if self.audience_type == "all":
            # Normalize: a whole-competition announcement carries no id list, so
            # a stored row can never imply a narrower audience than it has.
            self.audience_ids = []
        elif not self.audience_ids:
            raise ValueError(
                "Select at least one recipient for a targeted announcement"
            )
        return self


class AnnouncementUpdate(BaseModel):
    """Partial edit of a *scheduled* announcement (#349). Only the fields sent are
    applied (via ``model_fields_set``), mirroring ``HintUpdate`` — so
    ``publish_at: null`` releases it now while omitting it leaves the schedule
    untouched.

    Deliberately edits **content and timing only**, not the audience: ``audience_type``
    and ``audience_ids`` are coupled (the ids are type-specific), so a partial edit
    of one could silently desync them into a row that delivers to nobody. To retarget
    a scheduled announcement, cancel it and repost."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=5000)
    severity: Severity | None = None
    publish_at: datetime | None = None


class AnnouncementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    competition_id: str
    title: str
    body: str
    severity: str
    audience_type: str
    # Meaningful to staff (who see every announcement, including ones they sent
    # to a subset); a recipient only ever receives rows meant for them.
    audience_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    # Scheduled-publish state (#349). On the published feed ``hidden`` is always
    # false; the staff scheduled list carries hidden=true rows with a publish_at
    # so the UI can badge "Scheduled for …".
    hidden: bool = False
    publish_at: datetime | None = None

    @field_validator("audience_ids", mode="before")
    @classmethod
    def _ids_default(cls, v: object) -> object:
        # Null for "all" rows — present it as an empty list.
        return v or []
