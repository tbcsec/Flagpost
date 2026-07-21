"""Team routes (ROADMAP #7).

Nested under ``/api/competitions/{competition_id}/teams`` so every query is
scoped by the path's ``competition_id`` (§6.2) — there is no unscoped team
endpoint. Competitor actions (create/join/leave) need authentication plus
membership rules, not a catalog permission; the competition's
``participation_mode`` gates the whole surface (§11.3 — team-vs-individual is
per-competition configuration, not a module toggle).

Behavioural rules:
- One team per user per competition (DB-enforced, surfaced as 409).
- ``participation_mode='individual'`` competitions reject all team writes (400).
- Invite codes are returned only to team members (``/me``), never in listings.
- The creator is captain; if the captain leaves, the earliest-joined remaining
  member is promoted. When the last member leaves, the team is deleted (a
  memberless team would squat on its name and invite code).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user
from auth.membership import ensure_participant_role
from db import get_db
from models.competition import Competition
from models.team import Team, TeamMembership
from models.user import User
from schemas.team import (
    MyTeamOut,
    TeamCreate,
    TeamJoinRequest,
    TeamMemberOut,
    TeamOut,
)
from utils.event_bus import event_bus

router = APIRouter(
    prefix="/api/competitions/{competition_id}/teams", tags=["teams"]
)


async def _get_team_competition(
    db: AsyncSession, competition_id: str
) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    if competition.participation_mode != "team":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This competition is individual-mode; teams are disabled",
        )
    return competition


async def _membership_of(
    db: AsyncSession, competition_id: str, user_id: str
) -> TeamMembership | None:
    return await db.scalar(
        select(TeamMembership).where(
            TeamMembership.competition_id == competition_id,
            TeamMembership.user_id == user_id,
        )
    )


async def _my_team_out(db: AsyncSession, team: Team) -> MyTeamOut:
    rows = (
        await db.execute(
            select(TeamMembership, User.display_name)
            .join(User, User.id == TeamMembership.user_id)
            .where(TeamMembership.team_id == team.id)
            .order_by(TeamMembership.created_at)
        )
    ).all()
    return MyTeamOut(
        id=team.id,
        competition_id=team.competition_id,
        name=team.name,
        invite_code=team.invite_code,
        members=[
            TeamMemberOut(
                user_id=m.user_id, display_name=name, is_captain=m.is_captain
            )
            for m, name in rows
        ],
        created_at=team.created_at,
    )


@router.get("", response_model=list[TeamOut])
async def list_teams(
    competition_id: str,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TeamOut]:
    # Listing is allowed regardless of participation_mode (harmlessly empty for
    # individual competitions); scoped by competition_id per §6.2.
    rows = (
        await db.execute(
            select(Team, func.count(TeamMembership.id))
            .outerjoin(TeamMembership, TeamMembership.team_id == Team.id)
            .where(Team.competition_id == competition_id)
            .group_by(Team.id)
            .order_by(Team.created_at)
        )
    ).all()
    return [
        TeamOut(
            id=t.id,
            competition_id=t.competition_id,
            name=t.name,
            member_count=count,
            created_at=t.created_at,
        )
        for t, count in rows
    ]


@router.get("/me", response_model=MyTeamOut)
async def my_team(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTeamOut:
    membership = await _membership_of(db, competition_id, current_user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not in a team for this competition",
        )
    team = await db.get(Team, membership.team_id)
    return await _my_team_out(db, team)


@router.post("", response_model=MyTeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(
    competition_id: str,
    body: TeamCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTeamOut:
    await _get_team_competition(db, competition_id)

    if await _membership_of(db, competition_id, current_user.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already in a team for this competition",
        )
    name_taken = await db.scalar(
        select(Team).where(
            Team.competition_id == competition_id, Team.name == body.name
        )
    )
    if name_taken is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A team with that name already exists in this competition",
        )

    team = Team(competition_id=competition_id, name=body.name)
    db.add(team)
    await db.flush()
    db.add(
        TeamMembership(
            competition_id=competition_id,
            team_id=team.id,
            user_id=current_user.id,
            is_captain=True,
        )
    )
    await ensure_participant_role(db, competition_id, current_user.id)
    await db.commit()

    await event_bus.emit(
        "team.created",
        {
            "competition_id": competition_id,
            "team_id": team.id,
            "user_id": current_user.id,
            "name": team.name,
        },
    )
    return await _my_team_out(db, team)


@router.post("/join", response_model=MyTeamOut)
async def join_team(
    competition_id: str,
    body: TeamJoinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTeamOut:
    await _get_team_competition(db, competition_id)

    if await _membership_of(db, competition_id, current_user.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are already in a team for this competition",
        )
    # Scoped lookup: an invite code from another competition must not match.
    team = await db.scalar(
        select(Team).where(
            Team.competition_id == competition_id,
            Team.invite_code == body.invite_code,
        )
    )
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invite code"
        )

    db.add(
        TeamMembership(
            competition_id=competition_id,
            team_id=team.id,
            user_id=current_user.id,
        )
    )
    await ensure_participant_role(db, competition_id, current_user.id)
    await db.commit()

    await event_bus.emit(
        "team.member_joined",
        {
            "competition_id": competition_id,
            "team_id": team.id,
            "user_id": current_user.id,
        },
    )
    return await _my_team_out(db, team)


@router.post("/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_team(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    membership = await _membership_of(db, competition_id, current_user.id)
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You are not in a team for this competition",
        )
    team_id = membership.team_id
    was_captain = membership.is_captain
    await db.delete(membership)
    await db.flush()

    remaining = (
        await db.execute(
            select(TeamMembership)
            .where(TeamMembership.team_id == team_id)
            .order_by(TeamMembership.created_at)
        )
    ).scalars().all()

    team_deleted = False
    if not remaining:
        team = await db.get(Team, team_id)
        await db.delete(team)
        team_deleted = True
    elif was_captain:
        # Earliest-joined remaining member inherits the captaincy.
        remaining[0].is_captain = True

    await db.commit()

    await event_bus.emit(
        "team.member_left",
        {
            "competition_id": competition_id,
            "team_id": team_id,
            "user_id": current_user.id,
        },
    )
    if team_deleted:
        await event_bus.emit(
            "team.deleted",
            {
                "competition_id": competition_id,
                "team_id": team_id,
                "user_id": current_user.id,
            },
        )
