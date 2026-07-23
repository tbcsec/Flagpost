"""Award schemas (§5.3 — the manual counterpart to the ``create_award`` action).

An **Award** is a titled, described recognition that grants a point value folded
into the scoreboard. Judges hand them out manually from the participants roster
(``score_override``); the automation engine grants the same record via
``create_award``. Backed by ``models.automation.Achievement``.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class AwardCreate(BaseModel):
    # One award record is created per recipient (individual-mode subjects).
    user_ids: list[str] = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    points: int = Field(default=0, ge=-10000, le=10000)


class AwardOut(BaseModel):
    id: str
    title: str
    description: str | None
    points: int
    user_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
