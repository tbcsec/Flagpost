"""Pydantic schemas for hints (ROADMAP #15).

Two output shapes for the same hint, by audience:

- ``HintOut`` — the authoring/admin view: the body is always present.
- ``HintRevealOut`` — the competitor view: ``body`` is ``None`` until the
  requesting subject has revealed it (paying any cost), so an unrevealed hint's
  text never leaks to a competitor who hasn't unlocked it.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HintCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    cost: int = Field(default=0, ge=0, le=100000)


class HintOut(BaseModel):
    """Authoring view — body always included (requires challenge_edit)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    challenge_id: str
    body: str
    cost: int
    created_at: datetime


class HintRevealOut(BaseModel):
    """Competitor view — ``body`` is None until this subject has revealed it."""

    id: str
    challenge_id: str
    cost: int
    revealed: bool
    body: str | None = None
