"""Cumulative points-over-time timeline (#24 spectator board, #348 authed board).

A subject's score is the running sum of four sources (§13.2 + §5.3) — awarded
solves, hint-cost deductions, signed score adjustments, and award points. This
module turns those into a per-subject ``(timestamp, cumulative_points)`` series
for the top-N entrants, so a line chart can show *how* the standings got where
they are, not just where they are.

It is the single source of truth for both surfaces:

- the **public spectator** board (``utils/public_insights``) — always as of the
  freeze cutoff, top-10, no bracket;
- the **authenticated** scoreboard (``routers/scoreboard``) — bracket-scoped,
  staff can bypass the freeze, N configurable.

Two invariants, inherited from the board (``utils/scoreboard``):

- **Agrees with the table.** The series are computed from the same four sources,
  as of the same cutoff, so each line ends exactly on that subject's board total.
- **The freeze is absolute** on the read that passes ``live=False``: every point
  is filtered to ``created_at <= cutoff``, so a series never reveals movement the
  frozen board beside it is hiding.

For a long event the raw series is one point per scoring event — thousands of
points for thousands of solves. :func:`_downsample` bounds that to
``max_points`` per series (time-bucketed, endpoints preserved) so the payload
stays small without distorting the shape or the final total.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db import ensure_aware_utc, utcnow
from models.automation import Achievement
from models.challenge import Challenge
from models.competition import Competition
from models.hint import HintReveal
from models.score_adjustment import ScoreAdjustment
from models.submission import Submission
from utils.analytics import _solve_time_reference
from utils.scoreboard import compute_scoreboard, freeze_cutoff
from utils.scoring import challenge_value

# How many subjects the timeline plots by default. Ten is the CTFtime convention
# and the practical readability limit — beyond it the lines overlap into noise.
TIMELINE_SUBJECTS = 10
# Hard cap on how many subjects a caller may request (the authed endpoint's
# ``top`` param), so an over-large ``top_n`` can't turn one read into hundreds of
# series' worth of point queries.
MAX_TIMELINE_SUBJECTS = 25
# Cap on points *per series* after downsampling. Bounds the payload for a long
# event; below it a series is returned verbatim, so a typical event is unchanged.
TIMELINE_MAX_POINTS = 400

_AWARDED = (Submission.is_correct.is_(True), Submission.is_duplicate.is_(False))


def _subject_columns(team_mode: bool):
    """The (group-by column, scope filter) pair for each point source, matching
    the §13.2 subject semantics ``compute_scoreboard`` groups by: the credited
    team in team mode, the user (with a null team) in individual mode."""

    def pair(model):
        column = model.team_id if team_mode else model.user_id
        scope = model.team_id.isnot(None) if team_mode else model.team_id.is_(None)
        return column, scope

    return pair


async def awarded_solves(
    db: AsyncSession, competition: Competition, team_mode: bool, as_of
) -> list[tuple[str, str, Any, int]]:
    """Every awarded solve as ``(challenge_id, subject_id, created_at, value)``,
    valued exactly the way ``compute_scoreboard`` values it.

    Live (``as_of`` None): ``points_awarded`` is already current — the submit
    path re-values prior solvers whenever a dynamic challenge decays. Frozen:
    re-value each challenge by its solve count *as of the cutoff*, the CTFd
    freeze semantics ``_awarded_by_subject`` implements for the board itself.

    Known simplification (both paths): a dynamic challenge's *historical* worth
    isn't stored, so a series reflects current values applied backwards. It
    converges exactly on the board total, which is what the page must agree on.
    """
    column, scope = _subject_columns(team_mode)(Submission)
    conditions = [
        Submission.competition_id == competition.id,
        *_AWARDED,
        scope,
    ]
    if as_of is not None:
        conditions.append(Submission.created_at <= as_of)
    rows = (
        await db.execute(
            select(
                Submission.challenge_id,
                column,
                Submission.created_at,
                Submission.points_awarded,
            ).where(*conditions)
        )
    ).all()

    if as_of is None:
        return [(cid, sid, ts, int(pts or 0)) for cid, sid, ts, pts in rows]

    counts: dict[str, int] = {}
    for cid, _sid, _ts, _pts in rows:
        counts[cid] = counts.get(cid, 0) + 1
    challenges = {
        c.id: c
        for c in (
            await db.execute(
                select(Challenge).where(Challenge.competition_id == competition.id)
            )
        ).scalars()
    }
    valued = []
    for cid, sid, ts, _pts in rows:
        challenge = challenges.get(cid)
        value = challenge_value(challenge, counts[cid]) if challenge else 0
        valued.append((cid, sid, ts, value))
    return valued


async def _point_events(
    db: AsyncSession,
    competition: Competition,
    team_mode: bool,
    as_of,
    solves: list[tuple[str, str, Any, int]],
    wanted: set[str],
) -> dict[str, list[tuple[Any, int]]]:
    """Per-subject ``(when, delta)`` events from all four point sources, for the
    subjects in ``wanted``. Summing a subject's deltas reproduces its board total
    (before the board's clamp at zero)."""
    events: dict[str, list[tuple[Any, int]]] = {sid: [] for sid in wanted}

    for _cid, sid, ts, value in solves:
        if sid in events:
            events[sid].append((ensure_aware_utc(ts), value))

    pair = _subject_columns(team_mode)
    # (model, signed value column) — hint reveals *cost* points, the rest add.
    sources = (
        (HintReveal, HintReveal.cost_charged, -1),
        (ScoreAdjustment, ScoreAdjustment.points, 1),
        (Achievement, Achievement.points, 1),
    )
    for model, value_col, sign in sources:
        column, scope = pair(model)
        conditions = [model.competition_id == competition.id, scope]
        if as_of is not None:
            conditions.append(model.created_at <= as_of)
        rows = (
            await db.execute(
                select(column, model.created_at, value_col).where(*conditions)
            )
        ).all()
        for sid, ts, value in rows:
            if sid in events:
                events[sid].append((ensure_aware_utc(ts), sign * int(value or 0)))

    for series in events.values():
        series.sort(key=lambda event: event[0])
    return events


def _downsample(
    raw: list[tuple[datetime, int]], max_points: int
) -> list[tuple[datetime, int]]:
    """Bound a cumulative series to ``max_points`` points, keeping its shape.

    The first (baseline zero) and last (the board total) points are always kept
    exactly. The interior is time-bucketed into equal slices and the *last*
    point in each slice is kept — its cumulative value is exact at that instant,
    so the envelope and the ending total are preserved while the count is capped.
    A no-op when the series already fits, so a typical event is untouched.
    """
    if len(raw) <= max_points:
        return raw
    first, last = raw[0], raw[-1]
    # Fewer than three slots can't hold an interior bucket — keep just the
    # endpoints (the baseline zero and the board total). Returning the raw series
    # here would silently blow the cap, which is the one thing this must not do.
    if max_points < 3:
        return [first, last]
    t0 = first[0].timestamp()
    span = last[0].timestamp() - t0
    if span <= 0:  # every event at one instant — nothing meaningful to bucket
        return [first, last]
    buckets = max_points - 2  # reserve one slot each for the two endpoints
    kept: dict[int, tuple[datetime, int]] = {}
    for when, pts in raw[1:-1]:
        idx = int((when.timestamp() - t0) / span * buckets)
        if idx >= buckets:
            idx = buckets - 1
        kept[idx] = (when, pts)  # raw is time-sorted, so the later point wins
    return [first, *(kept[i] for i in sorted(kept)), last]


def _series_points(
    events: list[tuple[Any, int]], start, max_points: int | None
) -> list[dict[str, Any]]:
    """A running total as ``[{t, points}]``, clamped at zero like the board's
    ``net_points``. Seeded with a zero at ``start`` so every line begins on the
    baseline rather than at its first solve, then downsampled to ``max_points``."""
    raw: list[tuple[datetime, int]] = []
    if start is not None:
        raw.append((start, 0))
    running = 0
    for when, delta in events:
        running += delta
        raw.append((when, max(0, running)))
    if max_points is not None:
        raw = _downsample(raw, max_points)
    return [{"t": when.isoformat(), "points": pts} for when, pts in raw]


async def build_timeline(
    db: AsyncSession,
    competition: Competition,
    team_mode: bool,
    as_of,
    solves: list[tuple[str, str, Any, int]],
    entries: list[dict[str, Any]],
    *,
    top_n: int = TIMELINE_SUBJECTS,
    max_points: int | None = TIMELINE_MAX_POINTS,
) -> dict[str, Any]:
    """The timeline dict (``{start, end, series}``) for the top ``top_n`` of an
    already-computed, already-ranked ``entries`` list, reusing the caller's
    ``solves`` so the spectator path doesn't re-query them. ``entries`` carries
    any bracket filtering the board applied, so the timeline inherits it."""
    top = entries[:top_n]
    wanted = {entry["subject_id"] for entry in top}
    # Always a baseline: the scheduled start, or the competition's creation when
    # it was never scheduled, so every line starts at zero.
    start = _solve_time_reference(competition)
    events = (
        await _point_events(db, competition, team_mode, as_of, solves, wanted)
        if wanted
        else {}
    )
    return {
        "start": start.isoformat() if start is not None else None,
        # Frozen boards end at the cutoff; live ones run to now.
        "end": (as_of or utcnow()).isoformat(),
        "series": [
            {
                "subject_id": entry["subject_id"],
                "name": entry["name"],
                "points": _series_points(
                    events.get(entry["subject_id"], []), start, max_points
                ),
            }
            for entry in top
        ],
    }


# Short-lived in-process memo (ADR-0005 single process), mirroring the spectator
# insights cache: the authed board refetches on every activity ping, so a busy
# competition would recompute the same series for many watchers within a window.
# Keyed by (competition, live, bracket, top_n); TTL from settings (<= 0 disables
# it, which the tests do so a mutation is observable immediately). The returned
# dict is shared across hits — callers must treat it as read-only.
_cache: dict[str, dict[tuple, tuple[float, dict[str, Any]]]] = {}


def invalidate_timeline(competition_id: str) -> None:
    """Drop every cached timeline variant for a competition."""
    _cache.pop(competition_id, None)


async def compute_timeline(
    db: AsyncSession,
    competition: Competition,
    *,
    live: bool = False,
    bracket: str | None = None,
    top_n: int = TIMELINE_SUBJECTS,
    max_points: int | None = TIMELINE_MAX_POINTS,
) -> dict[str, Any]:
    """Standalone timeline for the authenticated scoreboard endpoint.

    Mirrors ``compute_scoreboard``'s ``live``/``bracket`` semantics: ``live``
    bypasses a freeze (a ``scoreboard_freeze`` holder's true view), ``bracket``
    scopes to one division and ranks within it. Computes the board to get the
    ranked, bracket-filtered top-N, then builds their series as of the same
    cutoff so chart and table can't disagree.
    """
    top_n = max(1, min(top_n, MAX_TIMELINE_SUBJECTS))
    ttl = settings.public_insights_cache_seconds
    # max_points is part of the key: it shapes the downsampled output, so a
    # caller varying it must not receive another cap's cached series.
    key = (live, bracket, top_n, max_points)
    if ttl > 0:
        cached = _cache.get(competition.id, {}).get(key)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]

    team_mode = competition.participation_mode == "team"
    as_of = None if live else freeze_cutoff(competition)
    board = await compute_scoreboard(db, competition, live=live, bracket=bracket)
    solves = await awarded_solves(db, competition, team_mode, as_of)
    timeline = await build_timeline(
        db,
        competition,
        team_mode,
        as_of,
        solves,
        board["entries"],
        top_n=top_n,
        max_points=max_points,
    )

    if ttl > 0:
        _cache.setdefault(competition.id, {})[key] = (
            time.monotonic() + ttl,
            timeline,
        )
    return timeline
