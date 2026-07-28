"""Analytics routes (ROADMAP #23) — read-only challenge & team reporting.

Competition-scoped (§6.2) and gated on ``view_competition_analytics`` (§7.1) —
staff-only (Judge holds it, Participant doesn't). The figures come from
``utils/analytics`` off already-recorded submission/hint/ticket data.

The ``analytics`` module is optional (§11.3), so the endpoints 404 when it's
disabled for the competition — the per-request enable gate, same as
automations/feedback.

The submissions browser (ROADMAP #76) lives here too, as the Submissions tab's
backing route — a raw, filterable read over ``submissions`` for dispute
resolution, gated on the narrower ``view_submissions`` permission rather than
``view_competition_analytics`` since raw payloads are more sensitive than
aggregate stats.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.competition import Competition
from models.submission import Submission
from models.user import User
from plugins.loader import is_module_enabled
from schemas.analytics import (
    ChallengeAnalyticsOut,
    TeamAnalyticsOut,
)
from schemas.submission import SubmissionCorrectness, SubmissionOut, SubmissionPage
from utils.analytics import challenge_analytics, subject_count, team_analytics

router = APIRouter(
    prefix="/api/competitions/{competition_id}/analytics", tags=["analytics"]
)


async def _competition_or_404(
    db: AsyncSession, competition_id: str
) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    if not await is_module_enabled(db, "analytics", competition_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The analytics module is disabled for this competition",
        )
    return competition


@router.get("/challenges", response_model=ChallengeAnalyticsOut)
async def challenge_report(
    competition_id: str,
    _user: User = Depends(require_permission("view_competition_analytics")),
    db: AsyncSession = Depends(get_db),
) -> ChallengeAnalyticsOut:
    competition = await _competition_or_404(db, competition_id)
    return ChallengeAnalyticsOut(
        mode=competition.participation_mode,
        subject_count=await subject_count(db, competition),
        challenges=await challenge_analytics(db, competition),
    )


@router.get("/teams", response_model=TeamAnalyticsOut)
async def team_report(
    competition_id: str,
    _user: User = Depends(require_permission("view_competition_analytics")),
    db: AsyncSession = Depends(get_db),
) -> TeamAnalyticsOut:
    competition = await _competition_or_404(db, competition_id)
    return TeamAnalyticsOut(
        mode=competition.participation_mode,
        teams=await team_analytics(db, competition),
    )


def _apply_submission_filters(
    stmt,
    *,
    competition_id: str,
    challenge_id: str | None,
    user_id: str | None,
    team_id: str | None,
    correctness: SubmissionCorrectness | None,
    q: str | None,
    since: datetime | None,
    until: datetime | None,
):
    stmt = stmt.where(Submission.competition_id == competition_id)
    if challenge_id:
        stmt = stmt.where(Submission.challenge_id == challenge_id)
    if user_id:
        stmt = stmt.where(Submission.user_id == user_id)
    if team_id:
        stmt = stmt.where(Submission.team_id == team_id)
    if correctness == SubmissionCorrectness.CORRECT:
        stmt = stmt.where(
            Submission.is_correct.is_(True), Submission.is_duplicate.is_(False)
        )
    elif correctness == SubmissionCorrectness.INCORRECT:
        stmt = stmt.where(Submission.is_correct.is_(False))
    elif correctness == SubmissionCorrectness.DUPLICATE:
        stmt = stmt.where(
            Submission.is_correct.is_(True), Submission.is_duplicate.is_(True)
        )
    if q:
        stmt = stmt.where(Submission.value.ilike(f"%{q}%"))
    if since:
        stmt = stmt.where(Submission.created_at >= since)
    if until:
        stmt = stmt.where(Submission.created_at <= until)
    return stmt


def _correctness_of(row: Submission) -> SubmissionCorrectness:
    if not row.is_correct:
        return SubmissionCorrectness.INCORRECT
    return (
        SubmissionCorrectness.DUPLICATE
        if row.is_duplicate
        else SubmissionCorrectness.CORRECT
    )


def _submission_out(row: Submission) -> SubmissionOut:
    return SubmissionOut(
        id=row.id,
        challenge_id=row.challenge_id,
        user_id=row.user_id,
        team_id=row.team_id,
        value=row.value,
        correctness=_correctness_of(row),
        points_awarded=row.points_awarded,
        created_at=row.created_at,
    )


@router.get("/submissions", response_model=SubmissionPage)
async def submission_browser(
    competition_id: str,
    challenge_id: str | None = None,
    user_id: str | None = None,
    team_id: str | None = None,
    correctness: SubmissionCorrectness | None = None,
    q: str | None = Query(None, description="Free-text search over the submitted value"),
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: User = Depends(require_permission("view_submissions")),
    db: AsyncSession = Depends(get_db),
) -> SubmissionPage:
    await _competition_or_404(db, competition_id)
    filters = dict(
        competition_id=competition_id,
        challenge_id=challenge_id,
        user_id=user_id,
        team_id=team_id,
        correctness=correctness,
        q=q,
        since=since,
        until=until,
    )
    total = await db.scalar(
        _apply_submission_filters(select(func.count(Submission.id)), **filters)
    )
    rows = (
        await db.execute(
            _apply_submission_filters(select(Submission), **filters)
            .order_by(Submission.created_at.desc(), Submission.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return SubmissionPage(
        items=[_submission_out(row) for row in rows],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/submissions/export")
async def submission_browser_export(
    competition_id: str,
    challenge_id: str | None = None,
    user_id: str | None = None,
    team_id: str | None = None,
    correctness: SubmissionCorrectness | None = None,
    q: str | None = Query(None, description="Free-text search over the submitted value"),
    since: datetime | None = None,
    until: datetime | None = None,
    _user: User = Depends(require_permission("view_submissions")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """CSV export of every submission matching the current filters (not just
    the current page) — for taking a dispute outside the platform."""
    await _competition_or_404(db, competition_id)
    rows = (
        await db.execute(
            _apply_submission_filters(
                select(Submission),
                competition_id=competition_id,
                challenge_id=challenge_id,
                user_id=user_id,
                team_id=team_id,
                correctness=correctness,
                q=q,
                since=since,
                until=until,
            ).order_by(Submission.created_at.desc(), Submission.id.desc())
        )
    ).scalars().all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["created_at", "challenge_id", "user_id", "team_id", "correctness", "value", "points_awarded"]
    )
    for row in rows:
        writer.writerow(
            [
                row.created_at.isoformat(),
                row.challenge_id,
                row.user_id,
                row.team_id or "",
                _correctness_of(row).value,
                row.value,
                row.points_awarded,
            ]
        )

    filename = f"submissions-{competition_id}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
