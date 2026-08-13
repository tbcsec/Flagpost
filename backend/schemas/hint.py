"""Pydantic schemas for hints (ROADMAP #15).

Two output shapes for the same hint, by audience:

- ``HintOut`` — the authoring/admin view: the body is always present, plus the
  ``hidden``/``release_at`` publish state (#213).
- ``HintRevealOut`` — the competitor view: ``body`` is ``None`` until the
  requesting subject has revealed it (paying any cost), so an unrevealed hint's
  text never leaks to a competitor who hasn't unlocked it. Hidden hints are
  filtered out entirely for competitors, so they never see one.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HintCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    cost: int = Field(default=0, ge=0, le=100000)
    # Author a hint hidden from competitors, to publish later (#213).
    hidden: bool = False
    # Optional scheduled publish time; the scheduler unhides at/after it.
    release_at: datetime | None = None


class HintUpdate(BaseModel):
    """Partial edit of a hint (authoring). Only the fields actually sent are
    applied (via ``model_fields_set``) — so ``release_at: null`` clears a
    schedule while omitting it leaves the schedule untouched. Setting
    ``hidden`` false publishes a hidden hint."""

    body: str | None = Field(default=None, min_length=1, max_length=2000)
    cost: int | None = Field(default=None, ge=0, le=100000)
    hidden: bool | None = None
    release_at: datetime | None = None


class HintOut(BaseModel):
    """Authoring view — body always included (requires challenge_edit)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    challenge_id: str
    body: str
    cost: int
    hidden: bool
    release_at: datetime | None
    created_at: datetime


class HintRevealOut(BaseModel):
    """Competitor view — ``body`` is None until this subject has revealed it."""

    id: str
    challenge_id: str
    cost: int
    revealed: bool
    body: str | None = None
    # Publish state, for the author list (a Hidden/Scheduled badge). Competitors
    # never receive a hidden hint, so for them this is always false / null.
    hidden: bool = False
    release_at: datetime | None = None
