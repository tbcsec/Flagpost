"""Post-event report aggregation (#134, ADR-0030, optional ``reports`` module).

Assembles the data a generated report renders from. Everything is read-only and
competition-scoped (§6.2); nothing here mutates or emits. Most figures reuse the
existing analytics/scoreboard aggregations (``utils.analytics``,
``utils.scoreboard``) so the report can't disagree with the live dashboards; the
new, report-specific computes (engagement funnel, solve velocity, hour-of-day
heatmap, score distribution, difficulty calibration, ticket response/resolution
times) live here.

Two deliberate choices, both for authoritative post-event numbers:

- Standings are read with ``live=True`` (``team_analytics``) — a report is
  produced after the event, so a lingering scoreboard freeze must not hide
  standings from the organiser (unlike the spectator ``public_insights``, which
  is freeze-aware).
- Time-bucketing and hour-of-day math run in Python, not SQL, so they stay
  portable across SQLite/Postgres (ADR-0006), the same discipline
  ``utils.analytics`` follows.

The section builders return plain JSON-serialisable structures keyed by a stable
section id; ``build_report_data`` runs only the requested sections and computes
the shared per-competition, per-challenge and per-subject datasets once.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import ensure_aware_utc, utcnow
from models.audit_log import AuditLogEntry
from models.challenge import Challenge
from models.competition import Competition
from models.feedback import ChallengeRating, Survey
from models.role import Role, RoleAssignment
from models.submission import Submission
from models.team import Team, TeamMembership
from models.ticket import Ticket, TicketMessage
from utils.analytics import challenge_analytics, subject_count, team_analytics
from utils.brackets import brackets_by_subject
from utils.feedback import survey_results

# The canonical section ids. A report requests a subset of these; the API/preset
# layer (a later stage) maps audience presets onto them. "overview" is the
# executive one-pager; the rest go deeper.
SECTIONS: tuple[str, ...] = (
    "overview",
    "participation",
    "results",
    "challenges",
    "support",
    "feedback",
)

# Human labels for the section picker (the API catalog surfaces these).
SECTION_LABELS: dict[str, str] = {
    "overview": "Executive summary",
    "participation": "Participation & engagement",
    "results": "Results & scoreboard",
    "challenges": "Challenge analysis",
    "support": "Support & operations",
    "feedback": "Feedback & sentiment",
}

# Audience presets — a bundle of sections the settings tab pre-selects; the
# organiser can still toggle individual sections. "executive" is the lean
# stakeholder read; "technical"/"full" go deep.
PRESETS: dict[str, list[str]] = {
    "executive": ["overview", "participation", "results"],
    "technical": list(SECTIONS),
    "full": list(SECTIONS),
}

# Only awarded (first-correct) submissions count as solves (§13.2). Redefined
# locally rather than importing utils.analytics._AWARDED — a one-line invariant,
# kept explicit so this module doesn't reach into another's private.
_AWARDED = (Submission.is_correct.is_(True), Submission.is_duplicate.is_(False))

# Calibration: how far a challenge's real solve rate may drift from the rate its
# difficulty tier implies before we flag it for re-tiering.
_CALIBRATION_TOLERANCE = 0.35


def _subject_col(competition: Competition):
    """The column the scoreboard credits — the team in team-mode, else the user."""
    return Submission.team_id if competition.participation_mode == "team" else Submission.user_id


def _registered_subjects(competition: Competition):
    """A subquery of the competition's registered scoring subjects — its teams
    (team-mode) or its Participant-role holders (individual). Used to keep the
    engagement funnel monotonic: only registered subjects count as "active", so a
    staff member who submits a test flag without joining can't push active/scored
    above registered."""
    if competition.participation_mode == "team":
        return select(Team.id).where(Team.competition_id == competition.id)
    return (
        select(RoleAssignment.user_id)
        .join(Role, Role.id == RoleAssignment.role_id)
        .where(
            RoleAssignment.competition_id == competition.id,
            Role.name == "Participant",
        )
    )


def _reference(competition: Competition) -> datetime:
    """When the event clock starts: the scheduled start, or creation if unscheduled."""
    return ensure_aware_utc(competition.start_at or competition.created_at)


async def _effective_end(db: AsyncSession, competition: Competition) -> datetime:
    """When the event effectively ended, for windowing.

    A scheduled end that has already passed is authoritative (activity after it is
    post-event staff testing, not play). Otherwise — a manually-stopped or
    never-scheduled competition, or one whose ``end_at`` is still in the future —
    the last submission is the real end, falling back to now. Never before the
    start."""
    now = utcnow()
    if competition.end_at is not None and ensure_aware_utc(competition.end_at) <= now:
        end = ensure_aware_utc(competition.end_at)
    else:
        last = await db.scalar(
            select(func.max(Submission.created_at)).where(
                Submission.competition_id == competition.id
            )
        )
        end = ensure_aware_utc(last) if last is not None else now
    # Never before the start, and never in the future (a still-future scheduled
    # start on an already-ended competition must not push the window ahead of when
    # activity actually happened).
    return min(max(end, _reference(competition)), now)


def _day_series(
    timestamps: list[datetime], start: datetime, end: datetime
) -> list[dict[str, Any]]:
    """Cumulative daily counts, one entry per UTC calendar day, so a chart has a
    continuous x-axis even on days with no activity.

    The range spans the *union* of [start, end] and the data's own extent, so a
    timestamp outside the nominal window (e.g. a pre-start registration, or a
    staff solve before kickoff) is still counted — the final ``cumulative`` always
    equals ``len(timestamps)`` and can't silently disagree with a grand total
    computed elsewhere."""
    aware = [ensure_aware_utc(ts) for ts in timestamps]
    per_day: dict[str, int] = {}
    for ts in aware:
        key = ts.date().isoformat()
        per_day[key] = per_day.get(key, 0) + 1
    lo = min([start, *aware]).date()
    hi = max([end, *aware]).date()
    days = max(1, (hi - lo).days + 1)
    out: list[dict[str, Any]] = []
    running = 0
    for i in range(days):
        key = (lo + timedelta(days=i)).isoformat()
        count = per_day.get(key, 0)
        running += count
        out.append({"date": key, "count": count, "cumulative": running})
    return out


# --- Section builders --------------------------------------------------------


async def _overview(
    db: AsyncSession,
    competition: Competition,
    challenges_data: list[dict[str, Any]],
    teams_data: list[dict[str, Any]],
    participants: int,
) -> dict[str, Any]:
    """The executive one-pager: headline counts + the few things that stood out."""
    published = [c for c in challenges_data if c["state"] == "published"]
    total_solves = sum(c["solve_count"] for c in challenges_data)
    # Every submission is grouped into challenge_analytics' attempt_count, so the
    # grand total is already in scope — no separate COUNT query.
    total_submissions = sum(c["attempt_count"] for c in challenges_data)
    teams = (
        (
            await db.scalar(
                select(func.count(Team.id)).where(Team.competition_id == competition.id)
            )
        )
        if competition.participation_mode == "team"
        else None
    )

    # "Solve rate" = the average fraction of subjects that solved each published
    # challenge (the intuitive headline number), distinct from submission accuracy.
    rates = [c["completion_rate"] for c in published]
    avg_completion_rate = round(sum(rates) / len(rates), 4) if rates else 0.0
    submission_accuracy = round(total_solves / total_submissions, 4) if total_submissions else 0.0

    # True mean of the raw ratings (a direct AVG), not a mean of already-rounded
    # per-challenge averages, which would drift.
    avg_rating_value = await db.scalar(
        select(func.avg(ChallengeRating.rating)).where(
            ChallengeRating.competition_id == competition.id
        )
    )
    avg_rating = round(float(avg_rating_value), 2) if avg_rating_value is not None else None

    solved = [c for c in published if c["solve_count"] > 0]
    attempted = [c for c in published if c["attempt_count"] > 0]
    most_solved = max(solved, key=lambda c: c["solve_count"], default=None)
    hardest = min(attempted, key=lambda c: c["completion_rate"], default=None)
    blood_leader = max(
        (t for t in teams_data if t["first_bloods"]),
        key=lambda t: t["first_bloods"],
        default=None,
    )

    return {
        "participants": participants,
        "teams": teams,
        "published_challenges": len(published),
        "total_solves": total_solves,
        "total_submissions": total_submissions,
        "avg_completion_rate": avg_completion_rate,
        "submission_accuracy": submission_accuracy,
        "avg_rating": avg_rating,
        "highlights": {
            "most_solved": (
                {"title": most_solved["title"], "solve_count": most_solved["solve_count"]}
                if most_solved
                else None
            ),
            "hardest": (
                {
                    "title": hardest["title"],
                    "solve_count": hardest["solve_count"],
                    "completion_rate": hardest["completion_rate"],
                }
                if hardest
                else None
            ),
            "first_blood_leader": (
                {"name": blood_leader["name"], "count": blood_leader["first_bloods"]}
                if blood_leader
                else None
            ),
        },
    }


async def _participation(
    db: AsyncSession, competition: Competition, end: datetime, registered: int
) -> dict[str, Any]:
    """Who took part, how far they got (funnel), and when they were active."""
    subject_col = _subject_col(competition)
    start = _reference(competition)
    # Only registered subjects count toward the funnel, so it narrows
    # monotonically (registered >= active >= scored) even if a non-participant
    # (e.g. staff testing) submitted.
    registered_only = [subject_col.in_(_registered_subjects(competition))]

    active = (
        await db.scalar(
            select(func.count(distinct(subject_col))).where(
                Submission.competition_id == competition.id,
                subject_col.is_not(None),
                *registered_only,
            )
        )
    ) or 0
    scored = (
        await db.scalar(
            select(func.count(distinct(subject_col))).where(
                Submission.competition_id == competition.id,
                subject_col.is_not(None),
                *registered_only,
                *_AWARDED,
            )
        )
    ) or 0
    final_day_start = end - timedelta(days=1)
    active_final_day = (
        await db.scalar(
            select(func.count(distinct(subject_col))).where(
                Submission.competition_id == competition.id,
                subject_col.is_not(None),
                *registered_only,
                Submission.created_at >= final_day_start,
                Submission.created_at <= end,
            )
        )
    ) or 0

    # Solve velocity: awarded-solve timestamps bucketed per day.
    solve_ts = (
        (
            await db.execute(
                select(Submission.created_at).where(
                    Submission.competition_id == competition.id, *_AWARDED
                )
            )
        )
        .scalars()
        .all()
    )
    solve_velocity = _day_series(list(solve_ts), start, end)

    # Hour-of-day heatmap: every submission attempt, counted by UTC hour (Python
    # so the hour extraction is dialect-independent).
    all_ts = (
        (
            await db.execute(
                select(Submission.created_at).where(
                    Submission.competition_id == competition.id
                )
            )
        )
        .scalars()
        .all()
    )
    hours = [0] * 24
    for ts in all_ts:
        hours[ensure_aware_utc(ts).hour] += 1

    # Registration curve: team creation (team-mode) or Participant-role grant.
    if competition.participation_mode == "team":
        reg_ts = (
            (
                await db.execute(
                    select(Team.created_at).where(Team.competition_id == competition.id)
                )
            )
            .scalars()
            .all()
        )
    else:
        reg_ts = (
            (
                await db.execute(
                    select(RoleAssignment.created_at)
                    .join(Role, Role.id == RoleAssignment.role_id)
                    .where(
                        RoleAssignment.competition_id == competition.id,
                        Role.name == "Participant",
                    )
                )
            )
            .scalars()
            .all()
        )

    # Team-size distribution (team-mode): member counts bucketed.
    team_sizes: dict[str, int] = {}
    if competition.participation_mode == "team":
        # Outer join so an empty team still yields a row (count 0) and the buckets
        # sum to the registered-team count rather than silently dropping it.
        size_rows = (
            await db.execute(
                select(Team.id, func.count(TeamMembership.id))
                .outerjoin(TeamMembership, TeamMembership.team_id == Team.id)
                .where(Team.competition_id == competition.id)
                .group_by(Team.id)
            )
        ).all()
        buckets = {"1": 0, "2-3": 0, "4-5": 0, "6+": 0}
        for _tid, n in size_rows:
            if n <= 1:
                buckets["1"] += 1
            elif n <= 3:
                buckets["2-3"] += 1
            elif n <= 5:
                buckets["4-5"] += 1
            else:
                buckets["6+"] += 1
        team_sizes = buckets

    return {
        "funnel": {
            "registered": registered,
            "active": active,
            "scored": scored,
            "active_final_day": active_final_day,
        },
        "solve_velocity": solve_velocity,
        "activity_by_hour": hours,
        "registration_curve": _day_series(list(reg_ts), start, end),
        "team_size_distribution": team_sizes,
    }


async def _results(
    db: AsyncSession,
    competition: Competition,
    teams_data: list[dict[str, Any]],
    top_n: int,
) -> dict[str, Any]:
    """Final standings, the score spread, and bracket winners."""
    subject_brackets = (
        await brackets_by_subject(db, competition.id) if competition.brackets else {}
    )
    standings = [
        {
            "rank": t["rank"],
            "subject_id": t["subject_id"],
            "name": t["name"],
            "points": t["points"],
            "solve_count": t["solve_count"],
            "first_bloods": t["first_bloods"],
            "bracket": subject_brackets.get(t["subject_id"]),
        }
        for t in teams_data
    ]

    # Score distribution: 10 equal-width bins across [0, max_points].
    points = [s["points"] for s in standings]
    max_points = max(points, default=0)
    bins: list[dict[str, Any]] = []
    if max_points > 0:
        bin_count = 10
        width = math.ceil(max_points / bin_count) or 1
        counts = [0] * bin_count
        for p in points:
            idx = min(p // width, bin_count - 1)
            counts[idx] += 1
        bins = [
            {"lo": i * width, "hi": (i + 1) * width, "count": counts[i]}
            for i in range(bin_count)
        ]

    # Bracket winners: the top-ranked subject in each configured bracket.
    bracket_winners: list[dict[str, Any]] = []
    for name in competition.brackets or []:
        top = next((s for s in standings if s["bracket"] == name), None)
        if top is not None:
            bracket_winners.append(
                {"bracket": name, "name": top["name"], "points": top["points"]}
            )

    return {
        "podium": standings[:3],
        "top": standings[: max(top_n, 3)],
        "full_standings": standings,
        "score_distribution": bins,
        "bracket_winners": bracket_winners,
    }


async def _challenges(
    db: AsyncSession,
    competition: Competition,
    challenges_data: list[dict[str, Any]],
    teams_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Per-challenge performance, category balance, and difficulty calibration."""
    diff_rows = (
        await db.execute(
            select(Challenge.id, Challenge.difficulty).where(
                Challenge.competition_id == competition.id
            )
        )
    ).all()
    difficulty = {cid: d for cid, d in diff_rows}

    published = [c for c in challenges_data if c["state"] == "published"]
    table = [{**c, "difficulty": difficulty.get(c["challenge_id"])} for c in published]

    # Category rollup: challenges, points on offer, and solves per category.
    rollup: dict[str, dict[str, Any]] = {}
    for c in published:
        cat = c["category"] or "Uncategorised"
        agg = rollup.setdefault(
            cat, {"category": cat, "challenge_count": 0, "points": 0, "solves": 0}
        )
        agg["challenge_count"] += 1
        agg["points"] += c["points"]
        agg["solves"] += c["solve_count"]
    category_rollup = sorted(rollup.values(), key=lambda r: r["solves"], reverse=True)

    # Difficulty calibration: compare each tiered challenge's real solve rate to
    # the rate its tier implies (tiers ordered easiest→hardest in the managed
    # vocab). Flag challenges that drift past the tolerance for re-tiering.
    tiers = list(competition.difficulty_tiers or [])
    calibration: list[dict[str, Any]] = []
    if tiers:
        n = len(tiers)
        for c in published:
            d = difficulty.get(c["challenge_id"])
            if d not in tiers or c["attempt_count"] == 0:
                continue
            idx = tiers.index(d)
            expected = 1 - (idx + 0.5) / n  # easiest tier → high expected solve rate
            drift = c["completion_rate"] - expected
            if abs(drift) >= _CALIBRATION_TOLERANCE:
                calibration.append(
                    {
                        "title": c["title"],
                        "difficulty": d,
                        "completion_rate": c["completion_rate"],
                        "expected_rate": round(expected, 3),
                        "direction": (
                            "easier_than_labelled"
                            if drift > 0
                            else "harder_than_labelled"
                        ),
                    }
                )

    never_solved = [
        {
            "title": c["title"],
            "category": c["category"],
            "attempt_count": c["attempt_count"],
        }
        for c in published
        if c["solve_count"] == 0
    ]

    first_bloods = [
        {"name": t["name"], "count": t["first_bloods"]}
        for t in teams_data
        if t["first_bloods"] > 0
    ]

    return {
        "table": table,
        "category_rollup": category_rollup,
        "difficulty_calibration": calibration,
        "never_solved": never_solved,
        "first_bloods": first_bloods,
    }


async def _support(
    db: AsyncSession, competition: Competition, end: datetime
) -> dict[str, Any]:
    """Ticket volume, responsiveness, and which challenges drove the load."""
    start = _reference(competition)

    tickets = (
        await db.execute(
            select(
                Ticket.id,
                Ticket.opener_user_id,
                Ticket.challenge_id,
                Ticket.status,
                Ticket.created_at,
            ).where(Ticket.competition_id == competition.id)
        )
    ).all()
    total_opened = len(tickets)
    resolved_status_ids = {t.id for t in tickets if t.status == "resolved"}
    resolved_count = len(resolved_status_ids)
    opened_at = {t.id: ensure_aware_utc(t.created_at) for t in tickets}
    opener = {t.id: t.opener_user_id for t in tickets}

    # First response: earliest non-internal message from someone other than the
    # opener. One pass over the competition's messages, oldest first.
    messages = (
        await db.execute(
            select(
                TicketMessage.ticket_id,
                TicketMessage.author_user_id,
                TicketMessage.is_internal,
                TicketMessage.created_at,
            )
            .where(TicketMessage.competition_id == competition.id)
            .order_by(TicketMessage.created_at, TicketMessage.id)
        )
    ).all()
    first_response_at: dict[str, datetime] = {}
    for m in messages:
        if m.ticket_id in first_response_at or m.ticket_id not in opener:
            continue
        if m.is_internal or m.author_user_id == opener[m.ticket_id]:
            continue
        first_response_at[m.ticket_id] = ensure_aware_utc(m.created_at)
    response_deltas = [
        (first_response_at[tid] - opened_at[tid]).total_seconds()
        for tid in first_response_at
    ]
    avg_first_response_seconds = (
        round(sum(response_deltas) / len(response_deltas)) if response_deltas else None
    )

    # Resolution time: derived from the audit log (there is no Ticket.resolved_at
    # column). Take the latest ticket.resolved event per ticket, matched in Python
    # so no dialect-specific JSON query is needed. Only tickets that are *still*
    # resolved count, so the average and resolved_count describe the same set (a
    # resolved-then-reopened ticket keeps its event but is now open).
    resolved_events = (
        await db.execute(
            select(AuditLogEntry.payload, AuditLogEntry.created_at)
            .where(
                AuditLogEntry.event_name == "ticket.resolved",
                AuditLogEntry.competition_id == competition.id,
            )
            .order_by(AuditLogEntry.created_at)
        )
    ).all()
    resolved_at: dict[str, datetime] = {}
    for payload, created in resolved_events:
        tid = (payload or {}).get("ticket_id")
        if tid in resolved_status_ids:
            resolved_at[tid] = ensure_aware_utc(created)  # ordered asc → keeps latest
    resolution_deltas = [
        (resolved_at[tid] - opened_at[tid]).total_seconds() for tid in resolved_at
    ]
    avg_resolution_seconds = (
        round(sum(resolution_deltas) / len(resolution_deltas))
        if resolution_deltas
        else None
    )

    # Tickets per challenge (null challenge_id = general support), busiest first.
    per_challenge: dict[str | None, int] = {}
    for t in tickets:
        per_challenge[t.challenge_id] = per_challenge.get(t.challenge_id, 0) + 1
    titles = dict(
        (
            await db.execute(
                select(Challenge.id, Challenge.title).where(
                    Challenge.competition_id == competition.id
                )
            )
        ).all()
    )
    by_challenge = sorted(
        (
            {
                "challenge_id": cid,
                "title": titles.get(cid) if cid else "General / account",
                "count": count,
            }
            for cid, count in per_challenge.items()
        ),
        key=lambda r: r["count"],
        reverse=True,
    )

    return {
        "total_opened": total_opened,
        "resolved_count": resolved_count,
        "avg_first_response_seconds": avg_first_response_seconds,
        "avg_resolution_seconds": avg_resolution_seconds,
        "tickets_by_challenge": by_challenge,
        "volume_over_time": _day_series(
            [ensure_aware_utc(t.created_at) for t in tickets], start, end
        ),
    }


async def _feedback(
    db: AsyncSession,
    competition: Competition,
    challenges_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Challenge ratings and post-event survey results (feedback module)."""
    ratings = sorted(
        (
            {
                "title": c["title"],
                "avg_rating": c["avg_rating"],
                "rating_count": c["rating_count"],
            }
            for c in challenges_data
            if c["rating_count"]
        ),
        key=lambda r: r["avg_rating"],
        reverse=True,
    )

    survey_ids = (
        (
            await db.execute(
                select(Survey.id).where(Survey.competition_id == competition.id)
            )
        )
        .scalars()
        .all()
    )
    surveys: list[dict[str, Any]] = []
    for sid in survey_ids:
        result = await survey_results(db, competition.id, sid)
        if result is not None:
            surveys.append(result.model_dump())

    return {"challenge_ratings": ratings, "surveys": surveys}


# --- Orchestrator ------------------------------------------------------------


async def build_report_data(
    db: AsyncSession,
    competition: Competition,
    *,
    sections: list[str],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the requested ``sections`` for ``competition`` into one payload.

    Unknown section ids are ignored. The shared per-competition (effective end,
    participant count), per-challenge and per-subject datasets are computed at
    most once and threaded into the builders that need them, so requesting several
    sections doesn't re-run the same aggregation.
    """
    options = options or {}
    requested = [s for s in sections if s in SECTIONS]
    # Clamp defensively: the create route bounds this, but a report re-renders from
    # stored config, so tolerate any bad value (non-numeric, NaN/inf) at render time.
    try:
        top_n = max(3, min(int(options.get("top_n", 10)), 100))
    except (TypeError, ValueError, OverflowError):
        top_n = 10

    end = await _effective_end(db, competition)
    participants = await subject_count(db, competition)
    result: dict[str, Any] = {
        "meta": {
            "competition_id": competition.id,
            "name": competition.name,
            "description": competition.description,
            "participation_mode": competition.participation_mode,
            "status": competition.status,
            "start_at": ensure_aware_utc(competition.start_at).isoformat()
            if competition.start_at
            else None,
            "end_at": ensure_aware_utc(competition.end_at).isoformat()
            if competition.end_at
            else None,
            "effective_end": end.isoformat(),
            "duration_days": max(1, (end.date() - _reference(competition).date()).days + 1),
            "brackets": list(competition.brackets or []),
            "sections": requested,
        }
    }

    needs_challenges = any(s in requested for s in ("overview", "challenges", "feedback"))
    needs_teams = any(s in requested for s in ("overview", "results", "challenges"))
    challenges_data = await challenge_analytics(db, competition) if needs_challenges else []
    # live=True so a lingering freeze can't hide final standings from the organiser.
    teams_data = await team_analytics(db, competition, live=True) if needs_teams else []

    for section in requested:
        if section == "overview":
            result["overview"] = await _overview(
                db, competition, challenges_data, teams_data, participants
            )
        elif section == "participation":
            result["participation"] = await _participation(db, competition, end, participants)
        elif section == "results":
            result["results"] = await _results(db, competition, teams_data, top_n)
        elif section == "challenges":
            result["challenges"] = await _challenges(
                db, competition, challenges_data, teams_data
            )
        elif section == "support":
            result["support"] = await _support(db, competition, end)
        elif section == "feedback":
            result["feedback"] = await _feedback(db, competition, challenges_data)

    return result
