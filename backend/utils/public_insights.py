"""Public (spectator) competition insights + points timeline (#24).

Deliberately separate from ``utils/analytics.py``: that module is staff-only and
**not** freeze-aware, whereas everything here is served to anyone with the link.
Keeping the public aggregation in one file makes "what do we disclose publicly"
reviewable at a glance.

Two invariants hold throughout:

- **The freeze is absolute.** The spectator board is computed as of
  ``freeze_cutoff`` (never ``live=True``), so every score-derived number here
  applies the same cutoff. A stat that counted post-freeze activity would leak
  exactly what the board beside it is hiding. Two figures are deliberately
  *not* cutoff-filtered, because neither is score movement and both already
  behave this way on the board itself: the **challenge inventory** (a freeze
  doesn't un-release a challenge) and the **participant count**
  (``compute_scoreboard`` lists every registered subject regardless of the
  cutoff, so a late joiner already shows up at zero points).
- **The timeline agrees with the table.** A subject's points come from four
  sources (§13.2 + §5.3): awarded solves, hint-cost deductions, signed score
  adjustments, and award points. All four become timeline events, so each
  series ends exactly on that subject's board total.

Only challenges that are **published and released** are counted, so the public
page never discloses drafts or an unreleased wave.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db import ensure_aware_utc, utcnow
from models.automation import Achievement
from models.challenge import Challenge
from models.competition import Competition
from models.hint import HintReveal
from models.score_adjustment import ScoreAdjustment
from models.submission import Submission
from utils.analytics import _solve_time_reference, subject_count
from utils.scoreboard import compute_scoreboard, freeze_cutoff
from utils.scoring import challenge_value

# How many subjects the timeline plots. Ten is the CTFtime convention and the
# practical readability limit — beyond it the lines overlap into noise — and it
# bounds the work this unauthenticated endpoint does.
TIMELINE_SUBJECTS = 10

_AWARDED = (Submission.is_correct.is_(True), Submission.is_duplicate.is_(False))

# Short-lived in-process memo (ADR-0005 single process). This endpoint is
# unauthenticated and can fan out to many spectators at once while the page
# polls every 30s, so collapsing concurrent viewers onto one computation is
# cheap insurance. Keyed by competition; TTL from settings (<= 0 disables it,
# which the tests do so they can observe a mutation immediately).
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _subject_columns(team_mode: bool):
    """The (group-by column, scope filter) pair for each point source, matching
    the §13.2 subject semantics ``compute_scoreboard`` groups by: the credited
    team in team mode, the user (with a null team) in individual mode."""

    def pair(model):
        column = model.team_id if team_mode else model.user_id
        scope = (
            model.team_id.isnot(None) if team_mode else model.team_id.is_(None)
        )
        return column, scope

    return pair


async def _visible_challenges(
    db: AsyncSession, competition_id: str
) -> list[tuple[str, str]]:
    """(id, title) for challenges a spectator may know about: published and past
    any scheduled release. Uses *now*, not the freeze cutoff — a scoreboard
    freeze stops the standings moving, it doesn't retract a released challenge."""
    now = utcnow()
    rows = (
        await db.execute(
            select(Challenge.id, Challenge.title, Challenge.release_at).where(
                Challenge.competition_id == competition_id,
                Challenge.state == "published",
            )
        )
    ).all()
    return [
        (cid, title)
        for cid, title, release_at in rows
        if release_at is None or ensure_aware_utc(release_at) <= now
    ]


async def _awarded_solves(
    db: AsyncSession, competition: Competition, team_mode: bool, as_of
) -> list[tuple[str, str, Any, int]]:
    """Every awarded solve as ``(challenge_id, subject_id, created_at, value)``,
    valued exactly the way ``compute_scoreboard`` values it.

    Live: ``points_awarded`` is already current — the submit path re-values
    prior solvers whenever a dynamic challenge decays. Frozen: re-value each
    challenge by its solve count *as of the cutoff*, the CTFd freeze semantics
    ``_awarded_by_subject`` implements for the board itself.

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
    subjects in ``wanted``. Summing a subject's deltas reproduces its board
    total (before the board's clamp at zero)."""
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


def _series_points(
    events: list[tuple[Any, int]], start
) -> list[dict[str, Any]]:
    """A running total as ``[{t, points}]``, clamped at zero like the board's
    ``net_points``. Seeded with a zero at the competition start so every line
    begins on the baseline rather than at its first solve."""
    points = [{"t": start.isoformat(), "points": 0}] if start is not None else []
    running = 0
    for when, delta in events:
        running += delta
        points.append({"t": when.isoformat(), "points": max(0, running)})
    return points


async def _timeline(
    db: AsyncSession,
    competition: Competition,
    team_mode: bool,
    as_of,
    solves: list[tuple[str, str, Any, int]],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    top = entries[:TIMELINE_SUBJECTS]
    wanted = {entry["subject_id"] for entry in top}
    # Always a baseline: the scheduled start, or the competition's creation when
    # it was never scheduled (``_solve_time_reference``), so every line starts
    # at zero instead of springing into existence at its first solve.
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
                "points": _series_points(events.get(entry["subject_id"], []), start),
            }
            for entry in top
        ],
    }


def _highlights(
    solves: list[tuple[str, str, Any, int]],
    attempts: dict[str, int],
    titles: dict[str, str],
    names: dict[str, str],
    reference,
) -> dict[str, Any]:
    """The "who/what stood out" cards. Every figure derives from the same
    freeze-filtered solve set as the stats, so they can't disagree."""
    solve_counts: dict[str, int] = {}
    for cid, _sid, _ts, _value in solves:
        if cid in titles:
            solve_counts[cid] = solve_counts.get(cid, 0) + 1

    most_solved = max(solve_counts.items(), key=lambda kv: kv[1], default=None)
    visible_attempts = {cid: n for cid, n in attempts.items() if cid in titles}
    most_attempted = max(
        visible_attempts.items(), key=lambda kv: kv[1], default=None
    )

    # First blood = the earliest awarded solve of each challenge.
    first_solver: dict[str, tuple[Any, str]] = {}
    for cid, sid, ts, _value in solves:
        when = ensure_aware_utc(ts)
        current = first_solver.get(cid)
        if cid in titles and (current is None or when < current[0]):
            first_solver[cid] = (when, sid)
    blood_counts: dict[str, int] = {}
    for _when, sid in first_solver.values():
        blood_counts[sid] = blood_counts.get(sid, 0) + 1
    leader = max(blood_counts.items(), key=lambda kv: kv[1], default=None)

    fastest = None
    for cid, sid, ts, _value in solves:
        if cid not in titles:
            continue
        seconds = max(0.0, (ensure_aware_utc(ts) - reference).total_seconds())
        if fastest is None or seconds < fastest["seconds"]:
            fastest = {
                "title": titles[cid],
                "name": names.get(sid, "—"),
                "seconds": seconds,
            }

    return {
        "most_solved": (
            {"title": titles[most_solved[0]], "count": most_solved[1]}
            if most_solved
            else None
        ),
        "most_attempted": (
            {"title": titles[most_attempted[0]], "count": most_attempted[1]}
            if most_attempted
            else None
        ),
        "first_blood_leader": (
            {"name": names.get(leader[0], "—"), "count": leader[1]}
            if leader
            else None
        ),
        "fastest_solve": fastest,
    }


async def public_insights(
    db: AsyncSession, competition: Competition
) -> dict[str, Any]:
    """Spectator insights + points timeline for a public competition (#24).

    Freeze-aware throughout (see the module docstring). The caller
    (routers/public_scoreboard.py) owns the opt-in/archived gating.
    """
    ttl = settings.public_insights_cache_seconds
    if ttl > 0:
        cached = _cache.get(competition.id)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]

    team_mode = competition.participation_mode == "team"
    as_of = freeze_cutoff(competition)
    board = await compute_scoreboard(db, competition)  # spectator = non-staff

    visible = await _visible_challenges(db, competition.id)
    titles = dict(visible)
    names = {e["subject_id"]: e["name"] for e in board["entries"]}
    solves = await _awarded_solves(db, competition, team_mode, as_of)

    attempt_conditions = [Submission.competition_id == competition.id]
    if as_of is not None:
        attempt_conditions.append(Submission.created_at <= as_of)
    attempt_rows = (
        await db.execute(
            select(Submission.challenge_id, func.count(Submission.id))
            .where(*attempt_conditions)
            .group_by(Submission.challenge_id)
        )
    ).all()
    attempts = {cid: int(n or 0) for cid, n in attempt_rows}

    solved_ids = {cid for cid, _sid, _ts, _v in solves if cid in titles}
    payload = {
        "frozen": board["frozen"],
        "frozen_at": board["frozen_at"],
        "stats": {
            "participants": await subject_count(db, competition),
            "solves": sum(1 for cid, *_ in solves if cid in titles),
            "challenges": len(visible),
            "unsolved": len(visible) - len(solved_ids),
        },
        "highlights": _highlights(
            solves, attempts, titles, names, _solve_time_reference(competition)
        ),
        "timeline": await _timeline(
            db, competition, team_mode, as_of, solves, board["entries"]
        ),
    }

    if ttl > 0:
        _cache[competition.id] = (time.monotonic() + ttl, payload)
    return payload
