"""Challenge instancing — competition-scoped routes (#266, ADR-0036).

Three audiences under one competition-scoped router:

- **Competitors** launch / poll / extend / destroy *their own* instance of a
  challenge (``instance_launch``). Launch is gated on the competition being
  ``running`` (#221) — staff with ``instance_manage`` bypass that to test-launch
  pre-publish — and force-disabled in demo mode (ADR-0036 §5).
- **Staff** list every running instance and force-kill any (``instance_view`` /
  ``instance_manage``).
- **Authors** attach the one deployment spec to a challenge (``challenge_edit``).

Every route first passes ``_guard``: the competition exists and the ``instances``
module is enabled for it (§11.3). Provisioning itself never happens here — the
launch route creates a ``requested`` row and the background lane takes it live
(``utils/instance_service``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission, user_has_permission
from config import settings as app_settings
from db import get_db
from models.challenge import Challenge
from models.challenge_instancing import (
    INSTANCE_ACTIVE_STATUSES,
    ChallengeDeployment,
    ChallengeInstance,
)
from models.competition import Competition
from models.team import Team
from models.user import User
from plugins.loader import is_module_enabled
from schemas.instances import (
    AdminInstanceOut,
    DeploymentOut,
    DeploymentUpdate,
    InstanceOut,
)
from utils.competition_status import gate_message, is_playable
from utils.event_bus import event_bus
from utils.instance_service import (
    InstanceError,
    extend,
    launch,
    teardown,
)
from utils.scoring import resolve_subject

router = APIRouter(prefix="/api/competitions/{competition_id}", tags=["instances"])


async def _guard(db: AsyncSession, competition_id: str) -> Competition:
    """The competition exists and the instances module is enabled for it."""
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    if not await is_module_enabled(db, "instances", competition_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The instances module is disabled for this competition",
        )
    return competition


async def _deployment_for(
    db: AsyncSession, competition_id: str, challenge_id: str
) -> ChallengeDeployment | None:
    return await db.scalar(
        select(ChallengeDeployment).where(
            ChallengeDeployment.competition_id == competition_id,
            ChallengeDeployment.challenge_id == challenge_id,
        )
    )


async def _active_for_subject(
    db: AsyncSession, competition_id: str, challenge_id: str, subject: str
) -> ChallengeInstance | None:
    return await db.scalar(
        select(ChallengeInstance)
        .where(
            ChallengeInstance.competition_id == competition_id,
            ChallengeInstance.challenge_id == challenge_id,
            ChallengeInstance.status.in_(INSTANCE_ACTIVE_STATUSES),
            func.coalesce(ChallengeInstance.team_id, ChallengeInstance.user_id)
            == subject,
        )
        .order_by(ChallengeInstance.created_at.desc())
        .limit(1)
    )


def _instance_out(instance: ChallengeInstance) -> InstanceOut:
    """Subject-facing view: connection details are revealed only once the
    instance is running (they're the allocation ledger before that)."""
    out = InstanceOut.model_validate(instance)
    if instance.status != "running":
        out.endpoints = []
    return out


# --- competitor: launch / status / extend / destroy --------------------------


@router.post(
    "/challenges/{challenge_id}/instance",
    response_model=InstanceOut,
    status_code=status.HTTP_201_CREATED,
)
async def launch_instance(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("instance_launch")),
    db: AsyncSession = Depends(get_db),
) -> InstanceOut:
    competition = await _guard(db, competition_id)
    if app_settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Launching instances is disabled on the demo.",
        )

    deployment = await _deployment_for(db, competition_id, challenge_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This challenge has no instance to launch.",
        )

    is_staff = await user_has_permission(
        db, current_user.id, "instance_manage", competition_id
    )
    # Play gate (#221): competitors launch only while running; staff test-launch
    # any time.
    if not is_playable(competition) and not is_staff:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=gate_message(competition.status),
        )

    subject = await resolve_subject(db, competition, current_user)
    if subject is None:
        if not is_staff:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Join a team before launching an instance.",
            )
        team_id = None  # staff test-launch is credited to the individual
    else:
        team_id = subject.team_id

    try:
        instance = await launch(
            db,
            competition=competition,
            deployment=deployment,
            user_id=current_user.id,
            team_id=team_id,
        )
    except InstanceError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _instance_out(instance)


@router.get(
    "/challenges/{challenge_id}/instance", response_model=InstanceOut
)
async def get_instance(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("instance_launch")),
    db: AsyncSession = Depends(get_db),
) -> InstanceOut:
    await _guard(db, competition_id)
    subject = await resolve_subject(db, await db.get(Competition, competition_id), current_user)
    subject_key = subject.team_id if subject and subject.team_id else current_user.id
    instance = await _active_for_subject(db, competition_id, challenge_id, subject_key)
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You have no running instance for this challenge.",
        )
    return _instance_out(instance)


@router.post(
    "/challenges/{challenge_id}/instance/extend", response_model=InstanceOut
)
async def extend_instance(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("instance_launch")),
    db: AsyncSession = Depends(get_db),
) -> InstanceOut:
    competition = await _guard(db, competition_id)
    subject = await resolve_subject(db, competition, current_user)
    subject_key = subject.team_id if subject and subject.team_id else current_user.id
    instance = await _active_for_subject(db, competition_id, challenge_id, subject_key)
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You have no running instance for this challenge.",
        )
    deployment = await db.get(ChallengeDeployment, instance.deployment_id)
    try:
        instance = await extend(db, instance, competition, deployment)
    except InstanceError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _instance_out(instance)


@router.delete(
    "/challenges/{challenge_id}/instance",
    status_code=status.HTTP_202_ACCEPTED,
)
async def destroy_instance(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("instance_launch")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    competition = await _guard(db, competition_id)
    subject = await resolve_subject(db, competition, current_user)
    subject_key = subject.team_id if subject and subject.team_id else current_user.id
    instance = await _active_for_subject(db, competition_id, challenge_id, subject_key)
    if instance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You have no running instance for this challenge.",
        )
    from db import SessionLocal

    await teardown(SessionLocal, instance.id)
    return {"status": "destroying"}


# --- staff: list + force-kill ------------------------------------------------


@router.get("/instances", response_model=list[AdminInstanceOut])
async def list_instances(
    competition_id: str,
    current_user: User = Depends(require_permission("instance_view")),
    db: AsyncSession = Depends(get_db),
) -> list[AdminInstanceOut]:
    await _guard(db, competition_id)
    rows = (
        await db.execute(
            select(ChallengeInstance)
            .where(
                ChallengeInstance.competition_id == competition_id,
                ChallengeInstance.status.in_(INSTANCE_ACTIVE_STATUSES),
            )
            .order_by(ChallengeInstance.created_at.desc())
        )
    ).scalars().all()

    # Resolve human labels server-side (ids stay on the row for correlation),
    # batched so the ops view costs no N+1. Subject names come from the users /
    # teams tables — not the competitor roster — so a staff test-launch shows the
    # staff member's name rather than a bare id.
    challenge_ids = {r.challenge_id for r in rows}
    team_ids = {r.team_id for r in rows if r.team_id}
    user_ids = {r.user_id for r in rows if not r.team_id}
    titles = (
        dict(
            (
                await db.execute(
                    select(Challenge.id, Challenge.title).where(
                        Challenge.id.in_(challenge_ids)
                    )
                )
            ).all()
        )
        if challenge_ids
        else {}
    )
    team_names = (
        dict(
            (
                await db.execute(
                    select(Team.id, Team.name).where(Team.id.in_(team_ids))
                )
            ).all()
        )
        if team_ids
        else {}
    )
    user_names = (
        dict(
            (
                await db.execute(
                    select(User.id, User.display_name).where(User.id.in_(user_ids))
                )
            ).all()
        )
        if user_ids
        else {}
    )
    out: list[AdminInstanceOut] = []
    for row in rows:
        row.challenge_title = titles.get(row.challenge_id)
        row.subject_label = (
            team_names.get(row.team_id)
            if row.team_id
            else user_names.get(row.user_id)
        )
        out.append(AdminInstanceOut.model_validate(row))
    return out


@router.delete(
    "/instances/{instance_id}", status_code=status.HTTP_202_ACCEPTED
)
async def kill_instance(
    competition_id: str,
    instance_id: str,
    current_user: User = Depends(require_permission("instance_manage")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _guard(db, competition_id)
    instance = await db.get(ChallengeInstance, instance_id)
    if instance is None or instance.competition_id != competition_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found"
        )
    from db import SessionLocal

    await teardown(SessionLocal, instance.id)
    return {"status": "destroying"}


# --- author: the per-challenge deployment spec -------------------------------


@router.get(
    "/challenges/{challenge_id}/deployment", response_model=DeploymentOut
)
async def get_deployment(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
) -> DeploymentOut:
    await _guard(db, competition_id)
    deployment = await _deployment_for(db, competition_id, challenge_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This challenge has no deployment spec.",
        )
    return DeploymentOut.model_validate(deployment)


@router.put(
    "/challenges/{challenge_id}/deployment", response_model=DeploymentOut
)
async def upsert_deployment(
    competition_id: str,
    challenge_id: str,
    body: DeploymentUpdate,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
) -> DeploymentOut:
    await _guard(db, competition_id)
    challenge = await db.get(Challenge, challenge_id)
    if challenge is None or challenge.competition_id != competition_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found"
        )
    error = body.validate_shape()
    if error is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=error
        )
    # A challenge can't have both its own static/regex/MCQ flag and a unique
    # per-instance flag — grading would silently use the per-instance flag and
    # ignore the authored one (ADR-0036 §3). Refuse the contradictory combo.
    if body.flag_mode == "unique_per_instance" and challenge.has_flag:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This challenge already has its own flag. Clear it before using "
                "unique per-instance flags — the two would conflict at grading."
            ),
        )

    deployment = await _deployment_for(db, competition_id, challenge_id)
    if deployment is None:
        deployment = ChallengeDeployment(
            competition_id=competition_id, challenge_id=challenge_id
        )
        db.add(deployment)
    for field, value in body.model_dump().items():
        setattr(deployment, field, value)
    await db.commit()
    await db.refresh(deployment)
    # A deployment change is a change to the challenge's configuration (§3.2):
    # reuse challenge.updated rather than mint a bespoke event.
    await event_bus.emit(
        "challenge.updated",
        {"competition_id": competition_id, "challenge_id": challenge_id},
    )
    return DeploymentOut.model_validate(deployment)


@router.delete(
    "/challenges/{challenge_id}/deployment",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_deployment(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _guard(db, competition_id)
    deployment = await _deployment_for(db, competition_id, challenge_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This challenge has no deployment spec.",
        )
    await db.delete(deployment)
    await db.commit()
    await event_bus.emit(
        "challenge.updated",
        {"competition_id": competition_id, "challenge_id": challenge_id},
    )
