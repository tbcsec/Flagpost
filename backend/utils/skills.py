"""Cross-competition skills web (#364, ADR-0039).

A competitor's *skill web* is the cumulative count of distinct challenges they've
solved, grouped by the **normalized name** of each challenge's category, summed
across **every** competition they've played — the HTB "the web grows one notch
per box" model. Unlike the scoreboard this is deliberately **not**
competition-scoped: it is the platform's first participant-facing consolidation
read (ADR-0039), so the cache can't key by ``competition_id`` and instead drops
wholesale on any solve.

:func:`compute_user_skills` builds one user's web (the ``/api/me/skills`` self
read). (An admin users×skills matrix was part of the original #364 ask but is
dropped for now — owner decision, ADR-0039 amendment.)

Category names are folded to the skill key **in Python** (:func:`normalize_skill`),
not in SQL, so SQLite (tests) and Postgres (prod) agree — the ADR-0006 parity
convention ``admin_overview``/``analytics`` already use. A challenge with no
category is excluded by the inner join to ``categories``.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.challenge import Category, Challenge
from models.submission import Submission

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


async def _cached(key: str, compute, db: AsyncSession, *args: Any) -> dict[str, Any]:
    ttl = settings.skills_cache_seconds
    now = time.monotonic()
    if ttl > 0:
        entry = _cache.get(key)
        if entry is not None and entry[0] > now:
            return entry[1]
    value = await compute(db, *args)
    if ttl > 0:
        _cache[key] = (now + ttl, value)
    return value
