"""Pydantic schemas for the competition entity (kept separate from models)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ParticipationMode = Literal["team", "individual"]
Visibility = Literal["public", "private"]


class CompetitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    start_at: datetime | None = None
    end_at: datetime | None = None
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    participation_mode: ParticipationMode = "team"
    visibility: Visibility = "private"


class CompetitionUpdate(BaseModel):
    """PATCH body — every field optional; only provided fields are applied."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    start_at: datetime | None = None
    end_at: datetime | None = None
    registration_opens_at: datetime | None = None
    registration_closes_at: datetime | None = None
    participation_mode: ParticipationMode | None = None
    visibility: Visibility | None = None


class CompetitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    start_at: datetime | None
    end_at: datetime | None
    registration_opens_at: datetime | None
    registration_closes_at: datetime | None
    participation_mode: ParticipationMode
    visibility: Visibility
    created_at: datetime
