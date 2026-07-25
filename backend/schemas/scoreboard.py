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
    # The subject's chosen bracket/division, or null (Phase 9, Group C).
    bracket: str | None = None


class ScoreboardOut(BaseModel):
    competition_id: str
    mode: str  # "team" | "individual"
    entries: list[ScoreboardEntry]
    # Scoreboard freeze (§13): true when these standings are a frozen snapshot;
    # frozen_at is the instant they stopped moving.
    frozen: bool = False
    frozen_at: datetime | None = None
    # The competition's bracket/division vocab (empty = no brackets).
    brackets: list[str] = []


class FreezeRequest(BaseModel):
    # When to freeze the board at. Omitted = now. A future time schedules the
    # freeze (the board keeps moving until it's reached).
    frozen_at: datetime | None = None


class PublicScoreboardOut(ScoreboardOut):
    """The spectator board (no login): the same standings plus enough context to
    render a standalone page. Only served for a ``public`` competition."""

    name: str
    start_at: datetime | None = None
    end_at: datetime | None = None


class PublicCompetitionOut(BaseModel):
    """A public-scoreboard competition in the /public directory."""

    id: str
    name: str
    participation_mode: str
    start_at: datetime | None = None
    end_at: datetime | None = None


# --- Public insights + points timeline (#24) ---------------------------------


class InsightStats(BaseModel):
    """Headline counts, all computed as of the freeze cutoff when frozen —
    except ``challenges``, the released inventory (a freeze stops the board
    moving, it doesn't retract a released challenge)."""

    participants: int
    solves: int
    challenges: int
    unsolved: int


class ChallengeHighlight(BaseModel):
    title: str
    count: int


class SubjectHighlight(BaseModel):
    name: str
    count: int


class FastestSolve(BaseModel):
    title: str
    name: str
    seconds: float


class InsightHighlights(BaseModel):
    """Each is null until the competition has the data to fill it."""

    most_solved: ChallengeHighlight | None = None
    most_attempted: ChallengeHighlight | None = None
    first_blood_leader: SubjectHighlight | None = None
    fastest_solve: FastestSolve | None = None


class TimelinePoint(BaseModel):
    t: datetime
    points: int


class TimelineSeries(BaseModel):
    subject_id: str
    name: str
    points: list[TimelinePoint]


class PointsTimeline(BaseModel):
    """Cumulative points per subject for the top entrants. Each series ends on
    that subject's board total — solves, hint costs, score adjustments and award
    points all contribute, exactly as the scoreboard folds them."""

    start: datetime | None = None
    end: datetime | None = None
    series: list[TimelineSeries] = []


class PublicInsightsOut(BaseModel):
    frozen: bool = False
    frozen_at: datetime | None = None
    stats: InsightStats
    highlights: InsightHighlights
    timeline: PointsTimeline
