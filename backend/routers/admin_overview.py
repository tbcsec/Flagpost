"""Site-admin overview (Admin → Dashboard).

The one sanctioned cross-competition read (§6.3): platform-wide totals plus each
competition's status + health, for a global Administrator. Gated on
``view_global_analytics`` (global-scoped, Administrator-only among the built-ins),
which existed in §7.1 but had no consumer until now.

All figures come from grouped aggregate queries over data other modules already
record — no new instrumentation, no migration. Status is derived in Python for
SQLite/Postgres parity (like the analytics module).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import ensure_aware_utc, get_db, utcnow
from models.challenge import Challenge
from models.competition import Competition
from models.role import Role, RoleAssignment
from models.submission import Submission
from models.team import Team
from models.ticket import Ticket
from models.user import User
from schemas.admin_overview import AdminOverview, CompetitionHealth

router = APIRouter(prefix="/api/admin", tags=["admin"])

_AWARDED = (Submission.is_correct.is_(True), Submission.is_duplicate.is_(False))


def _status(competition: Competition, now) -> str:
    """The admin-overview status label. Driven by the explicit gameplay status
    (#221), with `archived` overlaid and `not_started` split into `scheduled` (a
    future start_at is set) vs `draft` (none) for the operator's benefit."""
    if competition.archived_at is not None:
        return "archived"
    if competition.status == "ended":
        return "ended"
    if competition.status == "running":
        return "running"
    # not_started: distinguish a scheduled start from an unscheduled draft.
    # SQLite hands datetimes back naive; normalize before comparing (ADR-0006).
    start_at = ensure_aware_utc(competition.start_at) if competition.start_at else None
    return "scheduled" if start_at is not None and start_at > now else "draft"


async def _counts_by_competition(db: AsyncSession, stmt) -> dict[str, int]:
    """Run a `(competition_id, count)` grouped query into a plain dict."""
    return {cid: count for cid, count in (await db.execute(stmt)).all()}


@router.get("/overview", response_model=AdminOverview)
async def admin_overview(
    _user: User = Depends(require_permission("view_global_analytics")),
    db: AsyncSession = Depends(get_db),
) -> AdminOverview:
    now = utcnow()
    competitions = list((await db.scalars(select(Competition))).all())

    teams_by = await _counts_by_competition(
        db,
        select(Team.competition_id, func.count(Team.id)).group_by(Team.competition_id),
    )
    # Individual-mode roster size: distinct Participant-role holders (§7.5).
    participants_by = await _counts_by_competition(
        db,
        select(RoleAssignment.competition_id, func.count(distinct(RoleAssignment.user_id)))
        .join(Role, Role.id == RoleAssignment.role_id)
        .where(Role.name == "Participant", RoleAssignment.competition_id.is_not(None))
        .group_by(RoleAssignment.competition_id),
    )
    published_by = await _counts_by_competition(
        db,
        select(Challenge.competition_id, func.count(Challenge.id))
        .where(Challenge.state == "published")
        .group_by(Challenge.competition_id),
    )
    solves_by = await _counts_by_competition(
        db,
        select(Submission.competition_id, func.count(Submission.id))
        .where(*_AWARDED)
        .group_by(Submission.competition_id),
    )
    open_tickets_by = await _counts_by_competition(
        db,
        select(Ticket.competition_id, func.count(Ticket.id))
        .where(Ticket.status == "open")
        .group_by(Ticket.competition_id),
    )

    health = [
        CompetitionHealth(
            id=c.id,
            name=c.name,
            status=_status(c, now),
            visibility=c.visibility,
            participation_mode=c.participation_mode,
            participants=(
                teams_by.get(c.id, 0)
                if c.participation_mode == "team"
                else participants_by.get(c.id, 0)
            ),
            published_challenges=published_by.get(c.id, 0),
            solves=solves_by.get(c.id, 0),
            open_tickets=open_tickets_by.get(c.id, 0),
            created_at=c.created_at,
        )
        for c in competitions
    ]
    # Newest competitions first — the ones an admin is most likely watching.
    health.sort(key=lambda h: h.created_at, reverse=True)

    total_users = await db.scalar(select(func.count(User.id))) or 0
    active_users = (
        await db.scalar(select(func.count(User.id)).where(User.is_active.is_(True)))
        or 0
    )
    total_challenges = await db.scalar(select(func.count(Challenge.id))) or 0
    published_challenges = (
        await db.scalar(
            select(func.count(Challenge.id)).where(Challenge.state == "published")
        )
        or 0
    )
    total_submissions = await db.scalar(select(func.count(Submission.id))) or 0
    total_solves = (
        await db.scalar(select(func.count(Submission.id)).where(*_AWARDED)) or 0
    )

    return AdminOverview(
        total_users=total_users,
        active_users=active_users,
        total_competitions=len(competitions),
        active_competitions=sum(1 for c in competitions if c.archived_at is None),
        archived_competitions=sum(1 for c in competitions if c.archived_at is not None),
        total_teams=await db.scalar(select(func.count(Team.id))) or 0,
        total_challenges=total_challenges,
        published_challenges=published_challenges,
        total_submissions=total_submissions,
        total_solves=total_solves,
        competitions=health,
    )
