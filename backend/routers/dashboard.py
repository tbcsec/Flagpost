"""Operational dashboard read endpoints (ROADMAP #16, §10).

Each widget fetches its own data (§10.1), so this is a handful of small
read-only, competition-scoped (§6.2) endpoints rather than one payload:

- ``/stats`` and ``/recent-solves`` and ``/me`` gate on ``challenge_view`` —
  competitor-level aggregates every participant's dashboard shows.
- ``/challenge-health`` exposes attempt volume (failed submissions included),
  which is operational, so it gates on ``view_competition_analytics`` (staff).

All figures are derived from the submissions data scoring already records; no
new instrumentation.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission, user_has_permission
from db import get_db, utcnow
from utils.competition_status import has_started
from models.audit_log import AuditLogEntry
from models.challenge import Challenge
from models.challenge_instancing import ChallengeInstance, INSTANCE_ACTIVE_STATUSES
from models.competition import Competition
from models.dashboard_layout import DashboardLayout
from models.role import Role, RoleAssignment
from models.submission import Submission
from models.team import Team
from models.user import User
from pydantic import ValidationError

from schemas.dashboard import (
    BruteForceSubject,
    ChallengeHealth,
    DashboardLayoutOut,
    DashboardLayoutUpdate,
    DashboardStats,
    DifficultyProgress,
    InstanceFailure,
    InstanceHealth,
    InstanceStatusCount,
    LayoutEntry,
    ModerationEvent,
    MyStanding,
    RecentSolve,
    TeamActivity,
    UnsolvedChallenge,
)
from utils.scoreboard import compute_scoreboard, visible_solve_cutoff
from utils.scoring import resolve_subject, solved_challenge_ids

router = APIRouter(
    prefix="/api/competitions/{competition_id}/dashboard", tags=["dashboard"]
)

_AWARDED = (Submission.is_correct.is_(True), Submission.is_duplicate.is_(False))


async def _load_competition(db: AsyncSession, competition_id: str) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return competition


@router.get("/stats", response_model=DashboardStats)
async def dashboard_stats(
    competition_id: str,
    _user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> DashboardStats:
    competition = await _load_competition(db, competition_id)

    total_submissions = await db.scalar(
        select(func.count(Submission.id)).where(
            Submission.competition_id == competition_id
        )
    )
    total_solves = await db.scalar(
        select(func.count(Submission.id)).where(
            Submission.competition_id == competition_id, *_AWARDED
        )
    )
    recent_solves_1h = await db.scalar(
        select(func.count(Submission.id)).where(
            Submission.competition_id == competition_id,
            *_AWARDED,
            Submission.created_at >= utcnow() - timedelta(hours=1),
        )
    )
    published_challenges = await db.scalar(
        select(func.count(Challenge.id)).where(
            Challenge.competition_id == competition_id,
            Challenge.state == "published",
        )
    )
    if competition.participation_mode == "team":
        active_participants = await db.scalar(
            select(func.count(Team.id)).where(Team.competition_id == competition_id)
        )
    else:
        active_participants = await db.scalar(
            select(func.count(distinct(RoleAssignment.user_id)))
            .join(Role, Role.id == RoleAssignment.role_id)
            .where(
                RoleAssignment.competition_id == competition_id,
                Role.name == "Participant",
            )
        )

    return DashboardStats(
        total_solves=total_solves or 0,
        total_submissions=total_submissions or 0,
        active_participants=active_participants or 0,
        published_challenges=published_challenges or 0,
        recent_solves_1h=recent_solves_1h or 0,
    )


@router.get("/recent-solves", response_model=list[RecentSolve])
async def recent_solves(
    competition_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> list[RecentSolve]:
    competition = await _load_competition(db, competition_id)
    stmt = (
        select(
            Submission.team_id,
            Submission.user_id,
            Submission.points_awarded,
            Submission.created_at,
            Challenge.title,
        )
        .join(Challenge, Challenge.id == Submission.challenge_id)
        .where(Submission.competition_id == competition_id, *_AWARDED)
    )
    # A live ticker of subject + challenge + points is the frozen standings in
    # instalments, so it takes the same cutoff as the board itself.
    cutoff = await visible_solve_cutoff(db, competition, current_user)
    if cutoff is not None:
        stmt = stmt.where(Submission.created_at <= cutoff)
    # Staff test-solve before publishing, and `resolve_subject` gives any user a
    # subject in individual mode, so those attempts become awarded rows. Without
    # this the ticker names unreleased challenges — and their point value — to
    # competitors ahead of a scheduled wave. Every other competitor-facing read
    # of a challenge goes through `load_visible_challenge`, which applies the
    # same two conditions.
    can_edit = await user_has_permission(
        db, current_user.id, "challenge_edit", competition_id
    )
    # Competition status gate (#221): the ticker is solve data, so it tracks the
    # scoreboard — closed to competitors only before the competition starts (once
    # it ends, the same solves are public on the final board). Staff always see it.
    if not can_edit and not has_started(competition):
        return []
    if not can_edit:
        stmt = stmt.where(
            Challenge.state == "published",
            or_(Challenge.release_at.is_(None), Challenge.release_at <= utcnow()),
        )
    rows = (
        await db.execute(stmt.order_by(Submission.created_at.desc()).limit(10))
    ).all()

    # Resolve subject names in one query rather than per row.
    if competition.participation_mode == "team":
        ids = {r.team_id for r in rows if r.team_id}
        names = dict(
            (
                await db.execute(select(Team.id, Team.name).where(Team.id.in_(ids)))
            ).all()
        )
        name_for = lambda r: names.get(r.team_id, "—")  # noqa: E731
    else:
        ids = {r.user_id for r in rows}
        names = dict(
            (
                await db.execute(
                    select(User.id, User.display_name).where(User.id.in_(ids))
                )
            ).all()
        )
        name_for = lambda r: names.get(r.user_id, "—")  # noqa: E731

    return [
        RecentSolve(
            subject_name=name_for(r),
            challenge_title=r.title,
            points=r.points_awarded,
            at=r.created_at,
        )
        for r in rows
    ]


@router.get("/challenge-health", response_model=list[ChallengeHealth])
async def challenge_health(
    competition_id: str,
    _user: User = Depends(require_permission("view_competition_analytics")),
    db: AsyncSession = Depends(get_db),
) -> list[ChallengeHealth]:
    await _load_competition(db, competition_id)
    solves_sub = (
        select(
            Submission.challenge_id.label("cid"),
            func.count(Submission.id).label("solves"),
        )
        .where(Submission.competition_id == competition_id, *_AWARDED)
        .group_by(Submission.challenge_id)
        .subquery()
    )
    attempts_sub = (
        select(
            Submission.challenge_id.label("cid"),
            func.count(Submission.id).label("attempts"),
        )
        .where(Submission.competition_id == competition_id)
        .group_by(Submission.challenge_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                Challenge.id,
                Challenge.title,
                Challenge.points,
                solves_sub.c.solves,
                attempts_sub.c.attempts,
            )
            .outerjoin(solves_sub, solves_sub.c.cid == Challenge.id)
            .outerjoin(attempts_sub, attempts_sub.c.cid == Challenge.id)
            .where(Challenge.competition_id == competition_id)
            .order_by(Challenge.created_at)
        )
    ).all()
    return [
        ChallengeHealth(
            challenge_id=cid,
            title=title,
            points=points,
            solves=solves or 0,
            attempts=attempts or 0,
        )
        for cid, title, points, solves, attempts in rows
    ]


# --- New manager sections (#332) --------------------------------------------

# The subject a submission credits: the team in team-mode, the user otherwise.
def _subject_col(competition: Competition):
    return (
        Submission.team_id
        if competition.participation_mode == "team"
        else Submission.user_id
    )


async def _subject_names(
    db: AsyncSession, competition: Competition, ids: set[str]
) -> dict[str, str]:
    """Batch-resolve subject ids to display names (teams or users), one query."""
    if not ids:
        return {}
    if competition.participation_mode == "team":
        return dict(
            (await db.execute(select(Team.id, Team.name).where(Team.id.in_(ids)))).all()
        )
    return dict(
        (
            await db.execute(
                select(User.id, User.display_name).where(User.id.in_(ids))
            )
        ).all()
    )


@router.get("/unsolved-challenges", response_model=list[UnsolvedChallenge])
async def unsolved_challenges(
    competition_id: str,
    _user: User = Depends(require_permission("view_competition_analytics")),
    db: AsyncSession = Depends(get_db),
) -> list[UnsolvedChallenge]:
    """Published challenges with zero awarded solves, most-attempted first — the
    fast read on "what's too hard or broken" (complements challenge-health)."""
    await _load_competition(db, competition_id)
    solves_sub = (
        select(
            Submission.challenge_id.label("cid"),
            func.count(Submission.id).label("solves"),
        )
        .where(Submission.competition_id == competition_id, *_AWARDED)
        .group_by(Submission.challenge_id)
        .subquery()
    )
    attempts_sub = (
        select(
            Submission.challenge_id.label("cid"),
            func.count(Submission.id).label("attempts"),
        )
        .where(Submission.competition_id == competition_id)
        .group_by(Submission.challenge_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                Challenge.id,
                Challenge.title,
                Challenge.points,
                attempts_sub.c.attempts,
            )
            .outerjoin(solves_sub, solves_sub.c.cid == Challenge.id)
            .outerjoin(attempts_sub, attempts_sub.c.cid == Challenge.id)
            .where(
                Challenge.competition_id == competition_id,
                Challenge.state == "published",
                func.coalesce(solves_sub.c.solves, 0) == 0,
            )
            .order_by(
                func.coalesce(attempts_sub.c.attempts, 0).desc(), Challenge.created_at
            )
            .limit(15)
        )
    ).all()
    return [
        UnsolvedChallenge(
            challenge_id=cid, title=title, points=points, attempts=attempts or 0
        )
        for cid, title, points, attempts in rows
    ]


@router.get("/difficulty-progress", response_model=list[DifficultyProgress])
async def difficulty_progress(
    competition_id: str,
    _user: User = Depends(require_permission("view_competition_analytics")),
    db: AsyncSession = Depends(get_db),
) -> list[DifficultyProgress]:
    """Per difficulty tier, how many published challenges exist vs. are solved."""
    await _load_competition(db, competition_id)
    solved_sub = (
        select(Submission.challenge_id.label("cid"))
        .where(Submission.competition_id == competition_id, *_AWARDED)
        .group_by(Submission.challenge_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                Challenge.difficulty,
                func.count(Challenge.id).label("total"),
                func.count(solved_sub.c.cid).label("solved"),
            )
            .outerjoin(solved_sub, solved_sub.c.cid == Challenge.id)
            .where(
                Challenge.competition_id == competition_id,
                Challenge.state == "published",
            )
            .group_by(Challenge.difficulty)
            .order_by(func.count(Challenge.id).desc())
        )
    ).all()
    return [
        DifficultyProgress(difficulty=difficulty, total=total, solved=solved)
        for difficulty, total, solved in rows
    ]


@router.get("/team-activity", response_model=list[TeamActivity])
async def team_activity(
    competition_id: str,
    _user: User = Depends(require_permission("view_competition_analytics")),
    db: AsyncSession = Depends(get_db),
) -> list[TeamActivity]:
    """Subjects by submission volume + last-active time, most-recently-active
    first — the active/idle view. Subject = team (team mode) or participant."""
    competition = await _load_competition(db, competition_id)
    sid = _subject_col(competition)
    rows = (
        await db.execute(
            select(
                sid.label("sid"),
                func.count(Submission.id).label("submissions"),
                func.max(Submission.created_at).label("last_active"),
            )
            .where(Submission.competition_id == competition_id, sid.isnot(None))
            .group_by(sid)
            .order_by(func.max(Submission.created_at).desc())
            .limit(15)
        )
    ).all()
    names = await _subject_names(db, competition, {r.sid for r in rows})
    # A subject is idle when its most recent submission is older than the window
    # (or it has never submitted). Computed here so the widget needs no clock.
    idle_cutoff = utcnow() - timedelta(hours=1)
    return [
        TeamActivity(
            subject_id=r.sid,
            name=names.get(r.sid, "—"),
            submissions=r.submissions,
            last_active=r.last_active,
            idle=r.last_active is None or r.last_active < idle_cutoff,
        )
        for r in rows
    ]


@router.get("/brute-force", response_model=list[BruteForceSubject])
async def brute_force(
    competition_id: str,
    _user: User = Depends(require_permission("view_competition_analytics")),
    db: AsyncSession = Depends(get_db),
) -> list[BruteForceSubject]:
    """Subjects with the most wrong submissions (flag-guessing signal), highest
    first — only those with at least one wrong submission."""
    competition = await _load_competition(db, competition_id)
    sid = _subject_col(competition)
    wrong = func.sum(case((Submission.is_correct.is_(False), 1), else_=0))
    rows = (
        await db.execute(
            select(
                sid.label("sid"),
                wrong.label("wrong"),
                func.count(Submission.id).label("total"),
            )
            .where(Submission.competition_id == competition_id, sid.isnot(None))
            .group_by(sid)
            .having(wrong > 0)
            .order_by(wrong.desc())
            .limit(15)
        )
    ).all()
    names = await _subject_names(db, competition, {r.sid for r in rows})
    return [
        BruteForceSubject(
            subject_id=r.sid,
            name=names.get(r.sid, "—"),
            wrong=int(r.wrong or 0),
            total=r.total,
        )
        for r in rows
    ]


# Audit events worth surfacing on a competition-scoped moderation feed — the
# audit consumer records *every* event, so this allowlist is what keeps the feed
# high-signal (destructive actions, manual score changes, freeze, status flips).
# Global-only actions (site bans) are out of scope for a competition feed.
_MODERATION_EVENTS = frozenset(
    {
        "score.adjusted",
        "challenge.deleted",
        "category.deleted",
        "team.deleted",
        "scoreboard.frozen",
        "scoreboard.unfrozen",
        "competition.started",
        "competition.ended",
        "competition.archived",
    }
)


@router.get("/moderation-feed", response_model=list[ModerationEvent])
async def moderation_feed(
    competition_id: str,
    _user: User = Depends(require_permission("view_competition_analytics")),
    db: AsyncSession = Depends(get_db),
) -> list[ModerationEvent]:
    """Recent significant moderation actions in this competition (audit log,
    filtered to the allowlist). High-level summaries only — never raw payloads."""
    await _load_competition(db, competition_id)
    rows = (
        await db.execute(
            select(
                AuditLogEntry.event_name,
                AuditLogEntry.user_id,
                AuditLogEntry.created_at,
            )
            .where(
                AuditLogEntry.competition_id == competition_id,
                AuditLogEntry.event_name.in_(_MODERATION_EVENTS),
            )
            .order_by(AuditLogEntry.created_at.desc())
            .limit(15)
        )
    ).all()
    names = dict(
        (
            await db.execute(
                select(User.id, User.display_name).where(
                    User.id.in_({r.user_id for r in rows if r.user_id})
                )
            )
        ).all()
    )
    return [
        ModerationEvent(
            event_name=r.event_name,
            actor_name=names.get(r.user_id) if r.user_id else None,
            at=r.created_at,
        )
        for r in rows
    ]


@router.get("/instance-health", response_model=InstanceHealth)
async def instance_health(
    competition_id: str,
    _user: User = Depends(require_permission("instance_view")),
    db: AsyncSession = Depends(get_db),
) -> InstanceHealth:
    """Challenge-instancing runtime health (#266): active instances by lifecycle
    status plus recent failures. Empty when nothing is instanced."""
    await _load_competition(db, competition_id)
    status_rows = (
        await db.execute(
            select(ChallengeInstance.status, func.count(ChallengeInstance.id))
            .where(
                ChallengeInstance.competition_id == competition_id,
                ChallengeInstance.status.in_(INSTANCE_ACTIVE_STATUSES),
            )
            .group_by(ChallengeInstance.status)
        )
    ).all()
    fail_rows = (
        await db.execute(
            select(
                Challenge.title,
                ChallengeInstance.failure_reason,
                ChallengeInstance.created_at,
            )
            .join(Challenge, Challenge.id == ChallengeInstance.challenge_id)
            .where(
                ChallengeInstance.competition_id == competition_id,
                ChallengeInstance.status == "failed",
            )
            .order_by(ChallengeInstance.created_at.desc())
            .limit(8)
        )
    ).all()
    return InstanceHealth(
        active_by_status=[
            InstanceStatusCount(status=s, count=c) for s, c in status_rows
        ],
        failures=[
            InstanceFailure(challenge_title=title, reason=reason, at=at)
            for title, reason, at in fail_rows
        ],
    )


# Dashboards a saved layout may target (§10.3). Only the manager dashboard is
# customizable in this tier; the participant dashboard stays fixed. Kept as an
# allowlist so a client can't spray junk keys into the table.
_KNOWN_DASHBOARD_KEYS = frozenset({"manager"})


def _validate_key(dashboard_key: str) -> str:
    if dashboard_key not in _KNOWN_DASHBOARD_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown dashboard key: {dashboard_key}",
        )
    return dashboard_key


async def _get_layout_row(
    db: AsyncSession, user_id: str, dashboard_key: str
) -> DashboardLayout | None:
    return await db.scalar(
        select(DashboardLayout).where(
            DashboardLayout.user_id == user_id,
            DashboardLayout.dashboard_key == dashboard_key,
        )
    )


@router.get("/layout", response_model=DashboardLayoutOut | None)
async def get_layout(
    competition_id: str,
    dashboard_key: str = "manager",
    current_user: User = Depends(require_permission("customize_dashboard")),
    db: AsyncSession = Depends(get_db),
) -> DashboardLayoutOut | None:
    """The caller's saved layout for this dashboard, or null to fall back to the
    code-defined default (§10.5). Layout is per-user, not per-competition — the
    competition in the path only scopes the ``customize_dashboard`` check."""
    await _load_competition(db, competition_id)
    _validate_key(dashboard_key)
    row = await _get_layout_row(db, current_user.id, dashboard_key)
    if row is None:
        return None
    # Drop any entry that isn't in the current 2D shape rather than 500 on a
    # stored pre-#21 {cols,rows} layout: the client treats the remainder like a
    # partial save and fills in defaults, so an old layout cleanly resets.
    entries = []
    for raw in row.layout_json or []:
        try:
            entries.append(LayoutEntry.model_validate(raw))
        except ValidationError:
            continue
    return DashboardLayoutOut(dashboard_key=dashboard_key, entries=entries)


@router.put("/layout", response_model=DashboardLayoutOut)
async def put_layout(
    competition_id: str,
    payload: DashboardLayoutUpdate,
    dashboard_key: str = "manager",
    current_user: User = Depends(require_permission("customize_dashboard")),
    db: AsyncSession = Depends(get_db),
) -> DashboardLayoutOut:
    """Save (upsert) the caller's layout for this dashboard. Called on exit-edit,
    not per drag (§10.3). A personal preference, so no event is emitted."""
    await _load_competition(db, competition_id)
    _validate_key(dashboard_key)
    entries = [e.model_dump() for e in payload.entries]
    row = await _get_layout_row(db, current_user.id, dashboard_key)
    if row is None:
        row = DashboardLayout(
            user_id=current_user.id, dashboard_key=dashboard_key, layout_json=entries
        )
        db.add(row)
    else:
        row.layout_json = entries
    await db.commit()
    return DashboardLayoutOut(dashboard_key=dashboard_key, entries=payload.entries)


@router.delete("/layout", status_code=status.HTTP_204_NO_CONTENT)
async def delete_layout(
    competition_id: str,
    dashboard_key: str = "manager",
    current_user: User = Depends(require_permission("customize_dashboard")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Reset to default (§10.5): drop the saved layout so the code default
    applies again. Idempotent — deleting a non-existent layout is a no-op."""
    await _load_competition(db, competition_id)
    _validate_key(dashboard_key)
    row = await _get_layout_row(db, current_user.id, dashboard_key)
    if row is not None:
        await db.delete(row)
        await db.commit()


@router.get("/me", response_model=MyStanding)
async def my_standing(
    competition_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> MyStanding:
    competition = await _load_competition(db, competition_id)
    subject = await resolve_subject(db, competition, current_user)
    if subject is None:
        # A viewer with no scoring subject (e.g. team-mode without a team).
        return MyStanding(rank=None, points=None, solved_count=0)

    board = await compute_scoreboard(db, competition)
    entry = next(
        (e for e in board["entries"] if e["subject_id"] == subject.id), None
    )
    solved = await solved_challenge_ids(db, competition_id, subject)
    return MyStanding(
        rank=entry["rank"] if entry else None,
        points=entry["points"] if entry else 0,
        solved_count=len(solved),
    )
