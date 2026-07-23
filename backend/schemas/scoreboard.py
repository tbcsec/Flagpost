"""Pydantic schemas for the scoreboard (ROADMAP #13).

The same shape travels over REST (initial load) and the WebSocket room
(broadcast frames carry an extra ``type: "scoreboard"`` discriminator) — one
payload, two transports, so the client renders both identically.
"""

from datetime import datetime

from pydantic import BaseModel


class ScoreboardEntry(BaseModel):
    rank: int
    # The scoring subject: team id (team-mode) or user id (individual-mode).
    subject_id: str
    name: str
    points: int
    # When the subject reached its current score — the ranking tie-break.
    last_solve_at: datetime | None


class ScoreboardOut(BaseModel):
    competition_id: str
    mode: str  # "team" | "individual"
    entries: list[ScoreboardEntry]
    # Scoreboard freeze (§13): true when these standings are a frozen snapshot;
    # frozen_at is the instant they stopped moving.
    frozen: bool = False
    frozen_at: datetime | None = None


class FreezeRequest(BaseModel):
    # When to freeze the board at. Omitted = now. A future time schedules the
    # freeze (the board keeps moving until it's reached).
    frozen_at: datetime | None = None
