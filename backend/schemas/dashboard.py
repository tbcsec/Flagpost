"""Pydantic schemas for the operational dashboard (ROADMAP #16, §10).

Each widget fetches its own slice of data (§10.1), so the dashboard is a set of
small read shapes rather than one monolithic payload.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class DashboardStats(BaseModel):
    """Competition-wide aggregate counts for the manager stat tiles."""

    total_solves: int
    total_submissions: int
    active_participants: int  # teams (team mode) or participants (individual)
    published_challenges: int
    recent_solves_1h: int


class RecentSolve(BaseModel):
    subject_name: str  # team name (team mode) or display name (individual)
    challenge_title: str
    points: int
    at: datetime


class ChallengeHealth(BaseModel):
    challenge_id: str
    title: str
    points: int
    solves: int  # distinct solving subjects
    attempts: int  # all submissions, right or wrong


class MyStanding(BaseModel):
    """The requesting subject's own standing — null when they have no subject."""

    rank: int | None
    points: int | None
    solved_count: int


# --- Dashboard layout customization (§10.2–10.5, issue #21) -----------------
# The layout is opaque to the backend (§10.3): the frontend registry owns the
# widget catalog and per-widget minimum sizes, so we only validate shape and
# bounds. Entries are 2D placements on a 12-column grid: (x, y) position and
# (w, h) span in grid cells. `y`/`h` are unbounded in principle (the grid grows
# downward), so they carry a generous row cap only to reject absurd blobs.

_MAX_GRID = 12  # the dashboard grid is 12 columns wide
_MAX_ROWS = 200  # generous row ceiling — just a sanity bound, not a real limit


class LayoutEntry(BaseModel):
    widget_id: str = Field(min_length=1, max_length=64)
    x: int = Field(ge=0, le=_MAX_GRID)
    y: int = Field(ge=0, le=_MAX_ROWS)
    w: int = Field(ge=1, le=_MAX_GRID)
    h: int = Field(ge=1, le=_MAX_ROWS)
    hidden: bool = False


class DashboardLayoutOut(BaseModel):
    dashboard_key: str
    entries: list[LayoutEntry]


class DashboardLayoutUpdate(BaseModel):
    # Capped so a client can't persist an unbounded blob; the real dashboard has
    # a handful of widgets.
    entries: list[LayoutEntry] = Field(max_length=50)
