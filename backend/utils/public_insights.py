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
from models.challenge import Challenge
from models.competition import Competition
from models.submission import Submission
from utils.analytics import _solve_time_reference, subject_count
from utils.scoreboard import compute_scoreboard, freeze_cutoff
from utils.scoreboard_timeline import (
    TIMELINE_MAX_POINTS,
    TIMELINE_SUBJECTS,
    awarded_solves,
    build_timeline,
)

# Short-lived in-process memo (ADR-0005 single process). This endpoint is
# unauthenticated and can fan out to many spectators at once while the page
# polls every 30s, so collapsing concurrent viewers onto one computation is
# cheap insurance. Keyed by competition; TTL from settings (<= 0 disables it,
# which the tests do so they can observe a mutation immediately).
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
# Separate memo for the recent-activity feed (#77): venue mode polls it on a
# faster cadence than the insights page, so it has its own shorter TTL.
_activity_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _first_solvers(
    solves: list[tuple[str, str, Any, int]], titles: dict[str, str]
) -> dict[str, tuple[Any, str]]:
    """First blood per visible challenge: the earliest awarded solve, as
    ``{challenge_id: (when, subject_id)}``.

    The single definition of "first blood", shared by the highlight leaderboard
    (``_highlights``) and the recent-activity feed (``recent_activity``) so the
    two can never disagree about who drew first blood on a challenge."""
    first: dict[str, tuple[Any, str]] = {}
    for cid, sid, ts, _value in solves:
        if cid not in titles:
            continue
        when = ensure_aware_utc(ts)
        current = first.get(cid)
        if current is None or when < current[0]:
            first[cid] = (when, sid)
    return first


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

    # First blood = the earliest awarded solve of each challenge (shared helper).
    first_solver = _first_solvers(solves, titles)
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
    solves = await awarded_solves(db, competition, team_mode, as_of)

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
        "timeline": await build_timeline(
            db,
            competition,
            team_mode,
            as_of,
            solves,
            board["entries"],
            top_n=TIMELINE_SUBJECTS,
            max_points=TIMELINE_MAX_POINTS,
        ),
    }

    if ttl > 0:
        _cache[competition.id] = (time.monotonic() + ttl, payload)
    return payload


async def recent_activity(
    db: AsyncSession, competition: Competition, limit: int = 25
) -> dict[str, Any]:
    """The most recent awarded solves for the spectator surface (venue mode, #77).

    Newest-first, capped at ``limit``, each tagged ``is_first_blood`` via the
    same ``_first_solvers`` definition the highlight leaderboard uses. Only
    visible (published + released) challenges appear, and — like every figure in
    this module — it's computed as of ``freeze_cutoff``: a frozen competition
    emits nothing after the cutoff, so the venue splash stays silent during a
    freeze rather than leaking the movement the board is hiding.

    The caller (routers/public_scoreboard.py) owns the opt-in/archived gating.
    """
    ttl = settings.public_activity_cache_seconds
    if ttl > 0:
        cached = _activity_cache.get(competition.id)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]

    team_mode = competition.participation_mode == "team"
    as_of = freeze_cutoff(competition)
    board = await compute_scoreboard(db, competition)  # spectator = non-staff
    names = {e["subject_id"]: e["name"] for e in board["entries"]}
    titles = dict(await _visible_challenges(db, competition.id))
    solves = await awarded_solves(db, competition, team_mode, as_of)
    first_solver = _first_solvers(solves, titles)

    recent = sorted(
        (
            (cid, sid, ensure_aware_utc(ts), value)
            for cid, sid, ts, value in solves
            if cid in titles
        ),
        key=lambda row: row[2],
        reverse=True,
    )[:limit]

    payload = {
        "recent_solves": [
            {
                "challenge_id": cid,
                "title": titles[cid],
                "subject_name": names.get(sid, "—"),
                "solved_at": when.isoformat(),
                "points": value,
                # First blood only if this solve *is* the challenge's earliest —
                # a later solver of a first-blooded challenge is a plain solve.
                "is_first_blood": first_solver.get(cid) == (when, sid),
            }
            for cid, sid, when, value in recent
        ]
    }

    if ttl > 0:
        _activity_cache[competition.id] = (time.monotonic() + ttl, payload)
    return payload
