"""The jury console (#450, ADR-0042): what staff need to run the judge live.

* **See everything** (``judging_view``): every judging in the competition,
  filterable, with the queue's state; one submission's history of judgings.
* **Rejudge** (``judging_rejudge``) one submission, or every scored submission
  to a problem after a test case or limit was fixed. A rejudge is a **new**
  judging of the same code — history is never rewritten — and when it
  finishes, its verdict becomes the submission's: the worker reconciles the
  award (``utils.grading.regrade``), granting or revoking the points.
* **Override** (``judging_rejudge``) a verdict by hand, with a required
  reason: also a new judging (``origin = "override"``), recorded and shown as
  a judge's decision, never a silent edit. It counts at once.

Every action emits an event whose ``user_id`` is the staff member, so the audit
log attributes it; a newer judging always wins over an older one, so an
override stands until someone asks for a fresh rejudge.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from auth.deps import require_permission
from db import get_db, utcnow
from models.challenge import Challenge
from models.judge import JUDGE_SETTINGS_ID, JudgeSettings
from models.judging import ACTIVE_JUDGING_STATUSES, CodeSubmission, Judging
from models.team import Team
from models.user import User
from routers.judge_submissions import _competition_with_judge, _out
from schemas.judge import (
    JudgingOut,
    JudgingQueueOut,
    OverrideRequest,
    RejudgeAllOut,
    RejudgeAllRequest,
    StaffJudgingPage,
    StaffJudgingRow,
)
from utils import judge_worker
from utils.event_bus import event_bus
from utils.judge_live import push_judging

router = APIRouter(prefix="/api/competitions/{competition_id}", tags=["judging-staff"])

PAGE_MAX = 500


async def _judging(db: AsyncSession, competition_id: str, judging_id: str) -> Judging:
    judging = await db.scalar(
        select(Judging).where(Judging.id == judging_id, Judging.competition_id == competition_id)
    )
    if judging is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Judging not found")
    return judging


def _rejudge_of(judging: Judging, actor: User) -> Judging:
    return Judging(
        competition_id=judging.competition_id,
        code_submission_id=judging.code_submission_id,
        challenge_id=judging.challenge_id,
        user_id=judging.user_id,
        team_id=judging.team_id,
        kind=judging.kind,
        origin="rejudge",
        requested_by_user_id=actor.id,
        status="queued",
    )


async def _active(db: AsyncSession, code_submission_id: str) -> bool:
    return bool(
        await db.scalar(
            select(func.count(Judging.id)).where(
                Judging.code_submission_id == code_submission_id,
                Judging.status.in_(ACTIVE_JUDGING_STATUSES),
            )
        )
    )


# --- seeing --------------------------------------------------------------------------


@router.get("/judgings", response_model=StaffJudgingPage)
async def list_judgings(
    competition_id: str,
    challenge_id: str | None = None,
    verdict: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    kind: str | None = None,
    origin: str | None = None,
    subject: str | None = Query(default=None, description="a user or team id"),
    limit: int = Query(default=100, ge=1, le=PAGE_MAX),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_permission("judging_view")),
    db: AsyncSession = Depends(get_db),
) -> StaffJudgingPage:
    await _competition_with_judge(db, competition_id)
    requester = aliased(User)
    filters = [Judging.competition_id == competition_id]
    if challenge_id:
        filters.append(Judging.challenge_id == challenge_id)
    if verdict:
        filters.append(Judging.verdict == verdict)
    if status_:
        filters.append(Judging.status == status_)
    if kind:
        filters.append(Judging.kind == kind)
    if origin:
        filters.append(Judging.origin == origin)
    if subject:
        filters.append(or_(Judging.user_id == subject, Judging.team_id == subject))

    total = await db.scalar(select(func.count(Judging.id)).where(*filters)) or 0
    rows = (
        await db.execute(
            select(Judging, CodeSubmission, Challenge.title, User.display_name, Team.name,
                   requester.display_name)
            .join(CodeSubmission, CodeSubmission.id == Judging.code_submission_id)
            .join(Challenge, Challenge.id == Judging.challenge_id)
            .join(User, User.id == Judging.user_id)
            .outerjoin(Team, Team.id == Judging.team_id)
            .outerjoin(requester, requester.id == Judging.requested_by_user_id)
            .where(*filters)
            .order_by(Judging.created_at.desc(), Judging.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return StaffJudgingPage(
        total=total,
        items=[
            StaffJudgingRow(
                id=j.id,
                code_submission_id=j.code_submission_id,
                challenge_id=j.challenge_id,
                challenge_title=title,
                user_id=j.user_id,
                user_name=user_name,
                team_id=j.team_id,
                team_name=team_name,
                kind=j.kind,
                origin=j.origin,
                language_name=code.language_name,
                status=j.status,
                verdict=j.verdict,
                submitted_at=code.created_at,
                created_at=j.created_at,
                finished_at=j.finished_at,
                max_time_ms=j.max_time_ms,
                max_memory_kb=j.max_memory_kb,
                tests_passed=j.tests_passed,
                tests_total=j.tests_total,
                requested_by_name=req_name,
                note=j.note,
            )
            for j, code, title, user_name, team_name, req_name in rows
        ],
    )


@router.get("/judging-queue", response_model=JudgingQueueOut)
async def judging_queue(
    competition_id: str,
    current_user: User = Depends(require_permission("judging_view")),
    db: AsyncSession = Depends(get_db),
) -> JudgingQueueOut:
    await _competition_with_judge(db, competition_id)

    async def count(*where) -> int:
        return await db.scalar(select(func.count(Judging.id)).where(*where)) or 0

    here = Judging.competition_id == competition_id
    settings = await db.get(JudgeSettings, JUDGE_SETTINGS_ID)
    return JudgingQueueOut(
        queued=await count(here, Judging.status == "queued"),
        running=await count(here, Judging.status == "running"),
        # Site-wide on purpose (a count only): the judge is one queue, so other
        # competitions' work is what this competition's submissions wait behind.
        site_queued=await count(Judging.status == "queued"),
        site_running=await count(Judging.status == "running"),
        judge_enabled=bool(settings and settings.enabled),
        problems=await db.scalar(
            select(func.count(Challenge.id)).where(
                Challenge.competition_id == competition_id,
                Challenge.flag_type == "programming",
            )
        )
        or 0,
    )


@router.get("/code-submissions/{code_submission_id}/judgings", response_model=list[JudgingOut])
async def submission_history(
    competition_id: str,
    code_submission_id: str,
    current_user: User = Depends(require_permission("judging_view")),
    db: AsyncSession = Depends(get_db),
) -> list[JudgingOut]:
    """Every judging of one submission, oldest first: the original, rejudges
    and overrides."""
    await _competition_with_judge(db, competition_id)
    judgings = (
        await db.scalars(
            select(Judging)
            .where(
                Judging.code_submission_id == code_submission_id,
                Judging.competition_id == competition_id,
            )
            .order_by(Judging.created_at, Judging.id)
        )
    ).all()
    if not judgings:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    return [await _out(db, j, staff=True) for j in judgings]


# --- rejudging -------------------------------------------------------------------------


@router.post(
    "/judgings/{judging_id}/rejudge",
    response_model=JudgingOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rejudge_one(
    competition_id: str,
    judging_id: str,
    current_user: User = Depends(require_permission("judging_rejudge")),
    db: AsyncSession = Depends(get_db),
) -> JudgingOut:
    await _competition_with_judge(db, competition_id)
    judging = await _judging(db, competition_id, judging_id)
    if judging.kind != "submit":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only scored submissions are rejudged, not example runs"
        )
    if await _active(db, judging.code_submission_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This submission is already waiting to be judged"
        )
    new = _rejudge_of(judging, current_user)
    db.add(new)
    await db.commit()
    await event_bus.emit(
        "judging.rejudge_requested",
        {
            "competition_id": competition_id,
            "challenge_id": judging.challenge_id,
            "judging_id": new.id,
            "user_id": current_user.id,
            "count": 1,
        },
    )
    await push_judging(
        competition_id=competition_id, challenge_id=new.challenge_id,
        judging_id=new.id, user_id=new.user_id, status="queued",
    )
    judge_worker.wake()
    return await _out(db, new, staff=True)


@router.post(
    "/challenges/{challenge_id}/rejudge",
    response_model=RejudgeAllOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rejudge_problem(
    competition_id: str,
    challenge_id: str,
    body: RejudgeAllRequest,
    current_user: User = Depends(require_permission("judging_rejudge")),
    db: AsyncSession = Depends(get_db),
) -> RejudgeAllOut:
    """Judge every scored submission to a problem again — after a test case or
    a limit was fixed. Each gets a new judging; their verdicts replace the old
    ones as they finish. Submissions a judge decided by override are left
    alone (and counted): a bulk fix shouldn't silently reverse a deliberate
    decision — rejudge one individually to replace it."""
    await _competition_with_judge(db, competition_id)
    challenge = await db.scalar(
        select(Challenge).where(Challenge.id == challenge_id, Challenge.competition_id == competition_id)
    )
    if challenge is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Challenge not found")

    # Each submission's newest finished judging: its verdict and where it came
    # from. A submission with none yet (its first judging still running on the
    # old test data) is still rejudged.
    ranked = (
        select(
            Judging.code_submission_id.label("cs"),
            Judging.verdict.label("verdict"),
            Judging.origin.label("origin"),
            func.row_number()
            .over(
                partition_by=Judging.code_submission_id,
                order_by=(Judging.created_at.desc(), Judging.id.desc()),
            )
            .label("rn"),
        )
        .where(
            Judging.competition_id == competition_id,
            Judging.challenge_id == challenge_id,
            Judging.status == "done",
        )
        .subquery()
    )
    latest = select(ranked.c.cs, ranked.c.verdict, ranked.c.origin).where(ranked.c.rn == 1).subquery()
    rows = (
        await db.execute(
            select(CodeSubmission, latest.c.verdict, latest.c.origin)
            .outerjoin(latest, latest.c.cs == CodeSubmission.id)
            .where(
                CodeSubmission.competition_id == competition_id,
                CodeSubmission.challenge_id == challenge_id,
                CodeSubmission.kind == "submit",
            )
            .order_by(CodeSubmission.created_at, CodeSubmission.id)
        )
    ).all()
    # Only a judging still *waiting* means a rejudge is pointless: one already
    # running may be judging against the old test data, and a rejudge queued
    # now is newer, so its verdict wins.
    waiting = set(
        (
            await db.scalars(
                select(Judging.code_submission_id).where(
                    Judging.competition_id == competition_id,
                    Judging.challenge_id == challenge_id,
                    Judging.status == "queued",
                )
            )
        ).all()
    )
    queued: list[Judging] = []
    skipped = overridden = 0
    for code, verdict, origin in rows:
        if body.only == "accepted" and verdict != "accepted":
            continue
        if body.only == "not_accepted" and verdict == "accepted":
            continue
        if origin == "override":
            overridden += 1
            continue
        if code.id in waiting:
            skipped += 1
            continue
        new = Judging(
            competition_id=competition_id,
            code_submission_id=code.id,
            challenge_id=challenge_id,
            user_id=code.user_id,
            team_id=code.team_id,
            kind="submit",
            origin="rejudge",
            requested_by_user_id=current_user.id,
            status="queued",
        )
        db.add(new)
        queued.append(new)
    await db.commit()

    if queued:
        await event_bus.emit(
            "judging.rejudge_requested",
            {
                "competition_id": competition_id,
                "challenge_id": challenge_id,
                "judging_id": None,
                "user_id": current_user.id,
                "count": len(queued),
            },
        )
        for new in queued:
            await push_judging(
                competition_id=competition_id, challenge_id=challenge_id,
                judging_id=new.id, user_id=new.user_id, status="queued",
            )
        judge_worker.wake()
    return RejudgeAllOut(queued=len(queued), skipped=skipped, overridden=overridden)


# --- overriding ---------------------------------------------------------------------------


@router.post("/judgings/{judging_id}/override", response_model=JudgingOut)
async def override_verdict(
    competition_id: str,
    judging_id: str,
    body: OverrideRequest,
    current_user: User = Depends(require_permission("judging_rejudge")),
    db: AsyncSession = Depends(get_db),
) -> JudgingOut:
    """Decide a submission's verdict by hand. Recorded as a new judging marked
    as a judge's override with its reason — and it counts immediately."""
    await _competition_with_judge(db, competition_id)
    judging = await _judging(db, competition_id, judging_id)
    if judging.kind != "submit":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only scored submissions can be overridden, not example runs"
        )
    now = utcnow()
    new = Judging(
        competition_id=competition_id,
        code_submission_id=judging.code_submission_id,
        challenge_id=judging.challenge_id,
        user_id=judging.user_id,
        team_id=judging.team_id,
        kind="submit",
        origin="override",
        requested_by_user_id=current_user.id,
        note=body.reason,
        status="done",
        verdict=body.verdict,
        finished_at=now,
    )
    db.add(new)
    await db.flush()
    recorded = await judge_worker.record_verdict(db, new, body.verdict)
    await db.commit()

    await event_bus.emit(
        "judging.overridden",
        {
            "competition_id": competition_id,
            "challenge_id": new.challenge_id,
            "judging_id": new.id,
            "user_id": current_user.id,
            "submitter_user_id": new.user_id,
            "team_id": new.team_id,
            "verdict": body.verdict,
            "reason": body.reason,
        },
    )
    await judge_worker.emit_recorded(recorded, new)
    await push_judging(
        competition_id=competition_id, challenge_id=new.challenge_id,
        judging_id=new.id, user_id=new.user_id, status="done", verdict=body.verdict,
    )
    return await _out(db, new, staff=True)

