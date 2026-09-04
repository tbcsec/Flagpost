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
from models.team import Team, TeamApplication, TeamMembership
from models.user import User
from schemas.team import (
    MyTeamOut,
    TeamApplicationOut,
    TeamCreate,
    TeamJoinRequest,
    TeamJoinResult,
    TeamMemberOut,
    TeamOut,
    TeamUpdate,
)
from utils.competitions import (
    assert_email_verified_to_join,
    can_see_competition,
    get_visible_competition,
)
from utils.event_bus import event_bus
from utils.registration_fields import (
    get_values as get_registration_values,
    list_fields as list_registration_fields,
    set_values as set_registration_values,
    validate_values as validate_registration_values,
)
from utils.rules import require_rules_accepted

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
        affiliation=team.affiliation,
        country=team.country,
        website=team.website,
        approval_required=team.approval_required,
        created_at=team.created_at,
        field_values=await get_registration_values(
            db, team.competition_id, team.id
        ),
    )


@router.get("", response_model=list[TeamOut])
async def list_teams(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TeamOut]:
    # Visibility gate (GHSA-4mmf): a private competition's roster is not public.
    # 404 (not 403) so a private competition's existence isn't disclosed, matching
    # every other competition-scoped read (rules, registration_fields, ...).
    if await get_visible_competition(db, competition_id, current_user) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
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
            affiliation=t.affiliation,
            country=t.country,
            website=t.website,
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


@router.patch("/me", response_model=MyTeamOut)
async def update_my_team(
    competition_id: str,
    body: TeamUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTeamOut:
    """Edit your team's name/profile — captain only (Phase 9)."""
    membership = await _membership_of(db, competition_id, current_user.id)
    if membership is None or not membership.is_captain:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the team captain can edit the team",
        )
    team = await db.get(Team, membership.team_id)
    changes = body.model_dump(exclude_unset=True)
    # field_values isn't a Team column — pull it out and handle it separately
    # (#350) so the profile setattr loop below only touches real columns.
    field_values = changes.pop("field_values", None)
    if "name" in changes and changes["name"] != team.name:
        clash = await db.scalar(
            select(Team).where(
                Team.competition_id == competition_id,
                Team.name == changes["name"],
                Team.id != team.id,
            )
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A team with that name already exists in this competition",
            )
    for field, value in changes.items():
        setattr(team, field, value)
    if field_values is not None:
        reg_fields = await list_registration_fields(db, competition_id)
        cleaned = validate_registration_values(reg_fields, field_values)
        await set_registration_values(db, competition_id, team.id, cleaned)
    await db.commit()
    if field_values is not None:
        await event_bus.emit(
            "registration_field.value_set",
            {"competition_id": competition_id, "subject_id": team.id},
        )
    return await _my_team_out(db, team)


@router.post("", response_model=MyTeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(
    competition_id: str,
    body: TeamCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTeamOut:
    competition = await _get_team_competition(db, competition_id)
    # Entry gate (GHSA-4mmf): creating a team grants the Participant role, so it
    # is a self-serve *entry* into the competition and must honour the same
    # boundary as the join routes. A private competition is enterable only with
    # its invite code (via POST /competitions/join, which then makes the caller a
    # member) — never by POSTing a team with just the competition id. So allow
    # only when the caller can already see it: public, a global admin, or an
    # existing member. 404 (like the sibling reads) rather than 403 so a private
    # competition's existence stays undisclosed.
    if not await can_see_competition(db, competition, current_user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    # Email-verification gate (#74): parity with _join / join_team — a genuinely
    # new joiner needs a verified email when the site requires it.
    await assert_email_verified_to_join(db, competition, current_user)
    # Rules gate (#57): creating a team grants the Participant role just like
    # joining one, so it's the fourth join site (owner-confirmed) — without it,
    # "Create a team" on a public competition would bypass the rules entirely.
    await require_rules_accepted(db, competition, current_user)

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

    # Custom registration fields (#350): validate + enforce required before the
    # team exists, so a required-field miss fails cleanly with no orphan team.
    reg_fields = await list_registration_fields(db, competition_id)
    cleaned = (
        validate_registration_values(reg_fields, body.field_values)
        if reg_fields
        else {}
    )

    team = Team(
        competition_id=competition_id,
        name=body.name,
        affiliation=body.affiliation,
        country=body.country,
        website=body.website,
        approval_required=body.approval_required,
    )
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
    if cleaned:  # the team is the subject in team mode (§13.2)
        await set_registration_values(db, competition_id, team.id, cleaned)
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
    if cleaned:
        await event_bus.emit(
            "registration_field.value_set",
            {"competition_id": competition_id, "subject_id": team.id},
        )
    return await _my_team_out(db, team)


async def _assert_not_full(db: AsyncSession, competition: Competition, team_id: str) -> None:
    if competition.max_team_size is None:
        return
    members = await db.scalar(
        select(func.count(TeamMembership.id)).where(TeamMembership.team_id == team_id)
    )
    if (members or 0) >= competition.max_team_size:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This team is full"
        )


@router.post("/join", response_model=TeamJoinResult)
async def join_team(
    competition_id: str,
    body: TeamJoinRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TeamJoinResult:
    competition = await _get_team_competition(db, competition_id)
    # Email-verification gate (#74): parity with _join / create_team. No
    # visibility gate here — the team invite code in the body is the secret that
    # authorizes entry into a private competition (as the competition invite code
    # is for /competitions/join), so requiring can_see_competition would break
    # the legitimate team-invite path.
    await assert_email_verified_to_join(db, competition, current_user)
    # Rules gate (#57), deliberately ahead of the approval branch below: filing
    # a join *request* is the join moment for approval-required teams (owner
    # decision), so acceptance is required before an application exists.
    await require_rules_accepted(db, competition, current_user)

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

    await _assert_not_full(db, competition, team.id)

    # Approval-required teams: file (or reuse) a pending application instead.
    if team.approval_required:
        existing = await db.scalar(
            select(TeamApplication).where(
                TeamApplication.team_id == team.id,
                TeamApplication.user_id == current_user.id,
            )
        )
        if existing is None:
            db.add(
                TeamApplication(
                    competition_id=competition_id,
                    team_id=team.id,
                    user_id=current_user.id,
                )
            )
            await db.commit()
        return TeamJoinResult(pending=True)

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
    return TeamJoinResult(pending=False, team=await _my_team_out(db, team))


@router.get("/me/requests", response_model=list[TeamApplicationOut])
async def list_join_requests(
    competition_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TeamApplicationOut]:
    """Pending applications to the captain's team (Phase 9)."""
    membership = await _membership_of(db, competition_id, current_user.id)
    if membership is None or not membership.is_captain:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the captain can review join requests",
        )
    rows = (
        await db.execute(
            select(TeamApplication, User.display_name)
            .join(User, User.id == TeamApplication.user_id)
            .where(TeamApplication.team_id == membership.team_id)
            .order_by(TeamApplication.created_at)
        )
    ).all()
    return [
        TeamApplicationOut(
            id=a.id, user_id=a.user_id, display_name=name, created_at=a.created_at
        )
        for a, name in rows
    ]


async def _captain_application(
    db: AsyncSession, competition_id: str, user_id: str, application_id: str
) -> TeamApplication:
    membership = await _membership_of(db, competition_id, user_id)
    if membership is None or not membership.is_captain:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the captain can review join requests",
        )
    app = await db.get(TeamApplication, application_id)
    if app is None or app.team_id != membership.team_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Request not found"
        )
    return app


@router.post("/me/requests/{application_id}/approve", response_model=MyTeamOut)
async def approve_join_request(
    competition_id: str,
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyTeamOut:
    app = await _captain_application(db, competition_id, current_user.id, application_id)
    competition = await db.get(Competition, competition_id)
    await _assert_not_full(db, competition, app.team_id)
    # The applicant may have joined another team meanwhile — guard the invariant.
    if await _membership_of(db, competition_id, app.user_id) is None:
        db.add(
            TeamMembership(
                competition_id=competition_id, team_id=app.team_id, user_id=app.user_id
            )
        )
        await ensure_participant_role(db, competition_id, app.user_id)
    await db.delete(app)
    await db.commit()
    await event_bus.emit(
        "team.member_joined",
        {
            "competition_id": competition_id,
            "team_id": app.team_id,
            "user_id": app.user_id,
        },
    )
    return await _my_team_out(db, await db.get(Team, app.team_id))


@router.post("/me/requests/{application_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_join_request(
    competition_id: str,
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    app = await _captain_application(db, competition_id, current_user.id, application_id)
    await db.delete(app)
    await db.commit()


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
