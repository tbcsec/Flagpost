"""Cross-competition skills web (#364, ADR-0039).

A competitor's *skill web* is the cumulative count of distinct challenges they've
solved, grouped by the **normalized name** of each challenge's category, summed
across **every** competition they've played — the HTB "the web grows one notch
per box" model. Unlike the scoreboard this is deliberately **not**
competition-scoped: it is the platform's first participant-facing consolidation
read (ADR-0039), so the cache can't key by ``competition_id`` and instead drops
wholesale on any solve.

Two shapes, from the same aggregation:

- :func:`compute_user_skills` — one user's web (the ``/api/me/skills`` self read).
- :func:`compute_skill_matrix` — every user × skill (the admin matrix); the router
  paginates the returned ``users`` list, the shared ``skills`` axis rides along.

Category names are folded to the skill key **in Python** (:func:`normalize_skill`),
not in SQL, so SQLite (tests) and Postgres (prod) agree — the ADR-0006 parity
convention ``admin_overview``/``analytics`` already use. A challenge with no
category is excluded by the inner join to ``categories``.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db import ensure_aware_utc, utcnow
from models.challenge import Category, Challenge
from models.competition import Competition
from models.hint import HintReveal
from models.role import RoleAssignment
from models.submission import Submission
from models.user import User

# The awarded-solve predicate, shared with the scoreboard: a first correct solve,
# never a duplicate re-submit. Each awarded row is unique per (challenge, subject)
# by construction, and a challenge belongs to exactly one competition, so
# COUNT(DISTINCT challenge_id) is "distinct boxes owned" across every event.
_AWARDED = (Submission.is_correct.is_(True), Submission.is_duplicate.is_(False))


def normalize_skill(name: str) -> str:
    """The cross-competition skill key for a category name: whitespace-collapsed
    and lower-cased, folded **in Python** for SQLite/Postgres parity (ADR-0006).
    So ``"Web  Exploitation"`` in one event and ``"web exploitation"`` in another
    merge into one axis."""
    return " ".join(name.split()).lower()


def solve_weight() -> int:
    """How much one distinct solve adds to its skill axis. ``+1`` per box
    (ADR-0039): the only weight that composes across competitions — ``points`` and
    ``difficulty`` are per-competition vocab and don't normalize. A single seam so
    a future change (e.g. difficulty-weighted) is localized; a non-constant weight
    would sum a column in the queries below instead of scaling the distinct count."""
    return 1


async def compute_user_skills(db: AsyncSession, user_id: str) -> dict[str, Any]:
    """One user's skill web: ``{skills: [{skill, score}], total, competitions_played}``.

    ``score`` is the cumulative web value for that skill (distinct solves ×
    weight). Sorted by score descending, then skill name, so the caller can render
    the strongest axes first."""
    rows = (
        await db.execute(
            select(
                Category.name,
                func.count(func.distinct(Submission.challenge_id)),
            )
            .join(Challenge, Challenge.id == Submission.challenge_id)
            .join(Category, Category.id == Challenge.category_id)
            .where(Submission.user_id == user_id, *_AWARDED)
            .group_by(Category.name)
        )
    ).all()

    web: dict[str, int] = {}
    for name, count in rows:
        key = normalize_skill(name)
        web[key] = web.get(key, 0) + int(count or 0) * solve_weight()

    # Distinct events the user has scored in — the "across competitions" context
    # for the web. Reads Submission.competition_id directly (no join needed).
    competitions_played = int(
        await db.scalar(
            select(func.count(func.distinct(Submission.competition_id))).where(
                Submission.user_id == user_id, *_AWARDED
            )
        )
        or 0
    )

    skills = sorted(
        ({"skill": s, "score": v} for s, v in web.items()),
        key=lambda e: (-e["score"], e["skill"]),
    )
    return {
        "skills": skills,
        "total": sum(web.values()),
        "competitions_played": competitions_played,
    }


def _percentile(values: list[int], v: int) -> int:
    """Percentile rank of ``v`` within ``values`` (which includes ``v``): the
    share of *other* users strictly below. Deterministic, tie-stable, 0–100."""
    n = len(values)
    if n <= 1:
        return 0
    below = sum(1 for x in values if x < v)
    return round(100 * below / (n - 1))


# Allowlisted activity windows (#440): a bounded set so the cache keyspace stays
# bounded ("matrix:90", never "matrix:<arbitrary date>"). `None` = all time.
WINDOWS: dict[str, int | None] = {"all": None, "365": 365, "90": 90, "30": 30}


def _window_cutoff(window: str):
    """The inclusive lower bound for a window key, or None for all time. Callers
    validate the key against ``WINDOWS`` (the router 422s unknown values)."""
    days = WINDOWS[window]
    return None if days is None else utcnow() - timedelta(days=days)


async def _first_blood_counts(
    db: AsyncSession, cutoff
) -> tuple[dict[tuple[str, str], int], dict[str, str]]:
    """First bloods per (user, skill), plus the winner per challenge.

    First blood is a **historical fact** derived over all time — the earliest
    awarded submission per challenge (ties: created_at, then id, so SQLite and
    Postgres agree) — never recomputed inside a window, or the second solver
    would be crowned once the true first scrolls out. The window only decides
    which *earned* first bloods are counted (winning solve inside the window).
    """
    rows = (
        await db.execute(
            select(
                Submission.challenge_id,
                Submission.user_id,
                Submission.created_at,
                Submission.id,
                Category.name,
            )
            .join(Challenge, Challenge.id == Submission.challenge_id)
            .join(Category, Category.id == Challenge.category_id)
            .where(*_AWARDED)
        )
    ).all()
    winner: dict[str, tuple] = {}
    for challenge_id, user_id, created_at, sub_id, name in rows:
        key = (created_at, sub_id)
        held = winner.get(challenge_id)
        if held is None or key < (held[0], held[1]):
            winner[challenge_id] = (created_at, sub_id, user_id, normalize_skill(name))
    counts: dict[tuple[str, str], int] = {}
    winners_by_challenge: dict[str, str] = {}
    for challenge_id, (created_at, _sub_id, user_id, skill) in winner.items():
        winners_by_challenge[challenge_id] = user_id
        if cutoff is not None and created_at is not None:
            if ensure_aware_utc(created_at) < cutoff:
                continue
        counts[(user_id, skill)] = counts.get((user_id, skill), 0) + 1
    return counts, winners_by_challenge


async def compute_skill_matrix(db: AsyncSession, window: str = "all") -> dict[str, Any]:
    """Every user × skill, enriched (#435): per cell ``{weighted, solved,
    available, pct}`` —

    - ``weighted``: Σ ``points_awarded`` over awarded solves. The decay engine
      already priced rarity into each row at solve time, so this is the "sum a
      column" weighting the ``solve_weight`` seam anticipated. Points are
      per-competition vocab and do NOT normalize across events (the ADR-0039
      caveat) — which is why cross-user comparison happens via ``pct``, not raw
      weighted values.
    - ``solved`` / ``available``: distinct solves vs **published** challenges in
      that category across the competitions the user is a *member* of — coverage
      against genuine opportunity, immune to column-size bias.
    - ``pct``: percentile of ``weighted`` within the column over every tracked
      user (zeros included) — the scale-free comparator the heat map renders.

    Plus a ``population`` footer per skill (solver count + mean weighted among
    solvers). Computed whole so one cache entry serves every page; the router
    sorts + slices per request. Default order: total weighted desc, then name.

    v2 (#440): cells also carry ``attempts`` (every non-duplicate graded
    submission in the category — struggle on never-solved challenges included,
    that's signal), ``hints`` (reveals taken), and ``first_bloods`` (earned
    inside the window; the fact itself is derived over all time). ``window``
    bounds the *activity* (solves/attempts/hints); opportunity (``available``)
    is always current.
    """
    cutoff = _window_cutoff(window)
    awarded_where = list(_AWARDED)
    if cutoff is not None:
        awarded_where.append(Submission.created_at >= cutoff)
    rows = (
        await db.execute(
            select(
                Submission.user_id,
                User.display_name,
                Category.name,
                func.count(func.distinct(Submission.challenge_id)),
                func.coalesce(func.sum(Submission.points_awarded), 0),
            )
            .join(Challenge, Challenge.id == Submission.challenge_id)
            .join(Category, Category.id == Challenge.category_id)
            .join(User, User.id == Submission.user_id)
            .where(*awarded_where)
            .group_by(Submission.user_id, User.display_name, Category.name)
        )
    ).all()

    # Every graded attempt (right or wrong, never duplicates) per user×skill.
    attempts_where = [Submission.is_duplicate.is_(False)]
    if cutoff is not None:
        attempts_where.append(Submission.created_at >= cutoff)
    attempts_rows = (
        await db.execute(
            select(Submission.user_id, Category.name, func.count(Submission.id))
            .join(Challenge, Challenge.id == Submission.challenge_id)
            .join(Category, Category.id == Challenge.category_id)
            .where(*attempts_where)
            .group_by(Submission.user_id, Category.name)
        )
    ).all()
    attempts: dict[tuple[str, str], int] = {}
    for user_id, name, count in attempts_rows:
        key = (user_id, normalize_skill(name))
        attempts[key] = attempts.get(key, 0) + int(count or 0)

    # Hint reveals per user×skill.
    hints_where = []
    if cutoff is not None:
        hints_where.append(HintReveal.created_at >= cutoff)
    hints_rows = (
        await db.execute(
            select(HintReveal.user_id, Category.name, func.count(HintReveal.id))
            .join(Challenge, Challenge.id == HintReveal.challenge_id)
            .join(Category, Category.id == Challenge.category_id)
            .where(*hints_where)
            .group_by(HintReveal.user_id, Category.name)
        )
    ).all()
    hints: dict[tuple[str, str], int] = {}
    for user_id, name, count in hints_rows:
        key = (user_id, normalize_skill(name))
        hints[key] = hints.get(key, 0) + int(count or 0)

    first_bloods, _winners = await _first_blood_counts(db, cutoff)

    # Opportunity: published challenges per (competition, skill) — folded in
    # Python like everything else (ADR-0006 parity).
    availability_rows = (
        await db.execute(
            select(Challenge.competition_id, Category.name, func.count(Challenge.id))
            .join(Category, Category.id == Challenge.category_id)
            .where(Challenge.state == "published")
            .group_by(Challenge.competition_id, Category.name)
        )
    ).all()
    available: dict[tuple[str, str], int] = {}
    for competition_id, name, count in availability_rows:
        key = (competition_id, normalize_skill(name))
        available[key] = available.get(key, 0) + int(count or 0)

    # Membership: which competitions each user genuinely had access to. Any
    # competition-scoped role counts (Participant, Judge, custom) — opportunity
    # is about access, not role.
    membership_rows = (
        await db.execute(
            select(RoleAssignment.user_id, RoleAssignment.competition_id)
            .where(RoleAssignment.competition_id.is_not(None))
            .distinct()
        )
    ).all()
    memberships: dict[str, set[str]] = {}
    for user_id, competition_id in membership_rows:
        memberships.setdefault(user_id, set()).add(competition_id)

    axis: set[str] = set()
    users: dict[str, dict[str, Any]] = {}
    for user_id, display_name, name, count, weighted in rows:
        key = normalize_skill(name)
        axis.add(key)
        row = users.setdefault(
            user_id,
            {"user_id": user_id, "display_name": display_name, "scores": {}},
        )
        cell = row["scores"].setdefault(
            key,
            {
                "weighted": 0,
                "solved": 0,
                "available": 0,
                "pct": 0,
                "attempts": 0,
                "hints": 0,
                "first_bloods": 0,
            },
        )
        cell["solved"] += int(count or 0) * solve_weight()
        cell["weighted"] += int(weighted or 0)

    skills = sorted(axis)

    # Efficiency + first-blood signals attach to existing cells only — a cell
    # exists where there's a solve, so attempts on never-solved *categories*
    # surface in the drill-down, not the matrix (cell-existence rule, #435).
    for user_id, row in users.items():
        for skill, cell in row["scores"].items():
            cell["attempts"] = attempts.get((user_id, skill), 0)
            cell["hints"] = hints.get((user_id, skill), 0)
            cell["first_bloods"] = first_bloods.get((user_id, skill), 0)

    # Fill availability per user cell (their member competitions only), clamped
    # so an unpublished-after-solve challenge can't read as "3/0".
    for user_id, row in users.items():
        comps = memberships.get(user_id, set())
        for skill, cell in row["scores"].items():
            avail = sum(available.get((c, skill), 0) for c in comps)
            cell["available"] = max(avail, cell["solved"])

    # Column percentiles over every tracked user (zeros included): scale-free.
    for skill in skills:
        column = [u["scores"].get(skill, {}).get("weighted", 0) for u in users.values()]
        for row in users.values():
            cell = row["scores"].get(skill)
            if cell is not None:
                cell["pct"] = _percentile(column, cell["weighted"])

    population = {
        skill: {
            "solvers": sum(1 for u in users.values() if skill in u["scores"]),
            "mean_weighted": (
                round(
                    sum(u["scores"][skill]["weighted"] for u in users.values() if skill in u["scores"])
                    / max(sum(1 for u in users.values() if skill in u["scores"]), 1)
                )
            ),
        }
        for skill in skills
    }

    user_list = [
        {
            **row,
            "total": sum(c["solved"] for c in row["scores"].values()),
            "total_weighted": sum(c["weighted"] for c in row["scores"].values()),
        }
        for row in users.values()
    ]
    user_list.sort(key=lambda u: (-u["total_weighted"], (u["display_name"] or "").lower()))
    return {"skills": skills, "users": user_list, "population": population}


async def compute_user_skill_detail(
    db: AsyncSession, user_id: str, window: str = "all"
) -> dict[str, Any] | None:
    """One user's admin drill-down (#440): per-skill stats (the matrix cell plus
    efficiency) and their recent solve rows with full context. None for an
    unknown user (the router 404s). Same windowing rules as the matrix."""
    user = await db.get(User, user_id)
    if user is None:
        return None
    cutoff = _window_cutoff(window)

    awarded_where = [Submission.user_id == user_id, *_AWARDED]
    if cutoff is not None:
        awarded_where.append(Submission.created_at >= cutoff)
    solve_rows = (
        await db.execute(
            select(
                Submission.challenge_id,
                Challenge.title,
                Competition.name,
                Category.name,
                Submission.points_awarded,
                Submission.created_at,
            )
            .join(Challenge, Challenge.id == Submission.challenge_id)
            .join(Category, Category.id == Challenge.category_id)
            .join(Competition, Competition.id == Submission.competition_id)
            .where(*awarded_where)
            .order_by(Submission.created_at.desc())
        )
    ).all()

    # Per-challenge attempts + hints for this user, window-bounded like solves.
    attempts_where = [Submission.user_id == user_id, Submission.is_duplicate.is_(False)]
    if cutoff is not None:
        attempts_where.append(Submission.created_at >= cutoff)
    attempts_by_challenge = {
        row[0]: int(row[1] or 0)
        for row in (
            await db.execute(
                select(Submission.challenge_id, func.count(Submission.id))
                .where(*attempts_where)
                .group_by(Submission.challenge_id)
            )
        ).all()
    }
    hints_where = [HintReveal.user_id == user_id]
    if cutoff is not None:
        hints_where.append(HintReveal.created_at >= cutoff)
    hints_by_challenge = {
        row[0]: int(row[1] or 0)
        for row in (
            await db.execute(
                select(HintReveal.challenge_id, func.count(HintReveal.id))
                .where(*hints_where)
                .group_by(HintReveal.challenge_id)
            )
        ).all()
    }
    _counts, winners = await _first_blood_counts(db, cutoff)

    solves = []
    per_skill: dict[str, dict[str, int]] = {}
    for challenge_id, title, competition, category, points, created_at in solve_rows:
        skill = normalize_skill(category)
        solves.append(
            {
                "challenge_title": title,
                "competition_name": competition,
                "skill": skill,
                "points_awarded": int(points or 0),
                "attempts": attempts_by_challenge.get(challenge_id, 1),
                "hints": hints_by_challenge.get(challenge_id, 0),
                "first_blood": winners.get(challenge_id) == user_id,
                "solved_at": created_at,
            }
        )
        agg = per_skill.setdefault(
            skill,
            {"weighted": 0, "solved": 0, "attempts": 0, "hints": 0, "first_bloods": 0},
        )
        agg["weighted"] += int(points or 0)
        agg["solved"] += 1
        agg["first_bloods"] += 1 if winners.get(challenge_id) == user_id else 0

    # Category-level attempts/hints (includes struggle on never-solved
    # challenges, unlike the per-solve rows above).
    cat_rows = (
        await db.execute(
            select(Category.name, Challenge.id)
            .join(Challenge, Challenge.category_id == Category.id)
        )
    ).all()
    skill_of_challenge = {cid: normalize_skill(name) for name, cid in cat_rows}
    for challenge_id, n in attempts_by_challenge.items():
        skill = skill_of_challenge.get(challenge_id)
        if skill in per_skill:
            per_skill[skill]["attempts"] += n
    for challenge_id, n in hints_by_challenge.items():
        skill = skill_of_challenge.get(challenge_id)
        if skill in per_skill:
            per_skill[skill]["hints"] += n

    skills = sorted(
        ({"skill": k, **v} for k, v in per_skill.items()),
        key=lambda e: (-e["weighted"], e["skill"]),
    )
    return {
        "user_id": user_id,
        "display_name": user.display_name,
        "skills": skills,
        "solves": solves[:200],
        "total": sum(a["solved"] for a in per_skill.values()),
        "total_weighted": sum(a["weighted"] for a in per_skill.values()),
    }


# --- Cached read model (ADR-0039) --------------------------------------------
#
# Process-global TTL cache (single process, ADR-0005), mirroring the scoreboard/
# timeline caches — but keyed by ``user:<id>`` and a single ``matrix`` slot rather
# than by competition, because the web is cross-competition. ``invalidate_skills``
# drops EVERYTHING on any solve/category change: it can't know which users a solve
# touched without work, and a full clear is a cheap dict wipe (the scoring plugin's
# own over-invalidate rationale). Callers must treat the returned dict as read-only.

_cache: dict[str, tuple[float, Any]] = {}


def invalidate_skills() -> None:
    """Drop every cached web + the matrix. Wired to solve/category events so a new
    solve is reflected on the next read rather than after the TTL."""
    _cache.clear()


async def cached_user_skills(db: AsyncSession, user_id: str) -> dict[str, Any]:
    return await _cached(f"user:{user_id}", compute_user_skills, db, user_id)


async def cached_skill_matrix(db: AsyncSession, window: str = "all") -> dict[str, Any]:
    # Window keys are allowlisted (WINDOWS), so the keyspace stays bounded and
    # invalidate_skills' wholesale wipe still clears every variant.
    return await _cached(f"matrix:{window}", compute_skill_matrix, db, window)


async def cached_user_skill_detail(
    db: AsyncSession, user_id: str, window: str = "all"
) -> dict[str, Any] | None:
    return await _cached(f"detail:{user_id}:{window}", compute_user_skill_detail, db, user_id, window)


async def _cached(key: str, compute, db: AsyncSession, *args: Any) -> dict[str, Any]:
    ttl = settings.skills_cache_seconds
    now = time.monotonic()
    if ttl > 0:
        entry = _cache.get(key)
        if entry is not None and entry[0] > now:
            return entry[1]
    value = await compute(db, *args)
    # Never cache a miss: the detail read returns None for an unknown user, and
    # caching probes would let id-guessing grow the keyspace for no benefit.
    if ttl > 0 and value is not None:
        _cache[key] = (now + ttl, value)
    return value
