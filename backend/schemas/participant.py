"""Participant roster schema (ROADMAP #7 — individual-mode counterpart to teams).

Team-mode participation is browsed via the teams endpoints; individual-mode
competitions have no teams, so ``/participants`` is the "who's competing" surface
— every holder of the competition-scoped Participant role (§7.5) with their
individual standing. Names + standing only, matching what the scoreboard already
exposes (no new disclosure).
"""

from datetime import datetime

from pydantic import BaseModel


class ParticipantOut(BaseModel):
    user_id: str
    display_name: str
    joined_at: datetime
    rank: int | None  # null until they have a scored solve
    points: int
    solve_count: int
