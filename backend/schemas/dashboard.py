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


# --- New manager sections (#332) --------------------------------------------
# All staff-facing read slices, derived from data scoring/instancing already
# record; no new instrumentation. Each is a small competition-scoped endpoint.


class UnsolvedChallenge(BaseModel):
    """A published challenge with zero awarded solves (too hard, or broken)."""

    challenge_id: str
    title: str
    points: int
    attempts: int  # all submissions against it (0 solves + many attempts = hard)


class DifficultyProgress(BaseModel):
    """Per difficulty tier: how many published challenges exist vs. are solved."""

    difficulty: str | None  # the managed vocab value, or null → "Unspecified"
    total: int
    solved: int  # challenges with at least one awarded solve


class TeamActivity(BaseModel):
    """A subject (team, or participant in individual mode) with its submission
    volume and last-active time — drives the active/idle view. ``idle`` is
    computed server-side (last activity older than the idle window) so the client
    needs no wall-clock read."""

    subject_id: str
    name: str
    submissions: int
    last_active: datetime | None
    idle: bool


class BruteForceSubject(BaseModel):
    """A subject with a notable count of wrong submissions (flag-guessing signal)."""

    subject_id: str
    name: str
    wrong: int
    total: int


class ModerationEvent(BaseModel):
    """A significant moderation action in this competition, from the audit log."""

    event_name: str
    actor_name: str | None
    at: datetime


class InstanceStatusCount(BaseModel):
    status: str
    count: int


class InstanceFailure(BaseModel):
    challenge_title: str
    reason: str | None
    at: datetime


class InstanceHealth(BaseModel):
    """Challenge-instancing runtime health (#266): active instances by lifecycle
    status plus a short list of recent failures."""

    active_by_status: list[InstanceStatusCount]
    failures: list[InstanceFailure]


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
