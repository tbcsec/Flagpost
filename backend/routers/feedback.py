"""Feedback / survey routes (ROADMAP #22).

Nested under the competition (§6.2), in a per-competition-toggleable optional
module (§11.3) — every route 404s when the ``feedback`` module is disabled for
the competition. Three audiences, three permission gates:

- **Staff build surveys** (``feedback_manage``): survey + question CRUD,
  reorder, open/close.
- **Staff read results** (``feedback_view_responses``): aggregates + CSV export.
- **Competitors answer** (``feedback_submit``): list/read *open* surveys, submit
  one response per user, emitting ``survey.submitted`` — which, since the
  automation engine shipped (Phase 1), is a live trigger.

Reads (list/detail) allow any of the three, so a view-only observer role works.
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user, require_permission, user_has_permission
from db import get_db
from models.competition import Competition
from models.feedback import (
    Survey,
    SurveyAnswer,
    SurveyQuestion,
    SurveyResponse,
)
from models.user import User
from plugins.loader import is_module_enabled
from schemas.feedback import (
    QuestionCreate,
    QuestionOut,
    QuestionResults,
    ReorderQuestions,
    ResponseSubmit,
    SurveyCreate,
    SurveyDetail,
    SurveyResults,
    SurveySummary,
    SurveyUpdate,
)
from utils.event_bus import event_bus

router = APIRouter(
    prefix="/api/competitions/{competition_id}/surveys", tags=["feedback"]
)

_RATING_MAX = {"rating_1_10": 10, "rating_1_5": 5}


async def _guard(db: AsyncSession, competition_id: str) -> None:
    """Competition exists and the feedback module is enabled for it (§11.3)."""
    if await db.get(Competition, competition_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found")
    if not await is_module_enabled(db, "feedback", competition_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The feedback module is disabled for this competition",
        )


def _require_feedback_read():
    """Any of the three feedback permissions grants read access to surveys."""

    async def dependency(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        competition_id = request.path_params["competition_id"]
        for key in ("feedback_manage", "feedback_view_responses", "feedback_submit"):
            if await user_has_permission(db, current_user.id, key, competition_id):
                return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No feedback access"
        )

    return dependency


async def _survey_or_404(db: AsyncSession, competition_id: str, survey_id: str) -> Survey:
    survey = await db.scalar(
        select(Survey).where(Survey.id == survey_id, Survey.competition_id == competition_id)
    )
    if survey is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found")
    return survey


async def _questions(db: AsyncSession, survey_id: str) -> list[SurveyQuestion]:
    return list(
        (
            await db.execute(
                select(SurveyQuestion)
                .where(SurveyQuestion.survey_id == survey_id)
                .order_by(SurveyQuestion.position, SurveyQuestion.created_at)
            )
        )
        .scalars()
        .all()
    )


def _question_out(q: SurveyQuestion) -> QuestionOut:
    return QuestionOut(
        id=q.id, prompt=q.prompt, type=q.type, options=q.options or [],
        required=q.required, position=q.position,
    )


async def _response_count(db: AsyncSession, survey_id: str) -> int:
    return (
        await db.scalar(
            select(func.count(SurveyResponse.id)).where(
                SurveyResponse.survey_id == survey_id
            )
        )
    ) or 0


async def _detail(
    db: AsyncSession, survey: Survey, *, responded: bool | None
) -> SurveyDetail:
    questions = await _questions(db, survey.id)
    return SurveyDetail(
        id=survey.id, title=survey.title, description=survey.description,
        is_open=survey.is_open, question_count=len(questions),
        response_count=await _response_count(db, survey.id),
        created_at=survey.created_at,
        questions=[_question_out(q) for q in questions],
        responded=responded,
    )


async def _has_responded(db: AsyncSession, survey_id: str, user_id: str) -> bool:
    return (
        await db.scalar(
            select(SurveyResponse.id).where(
                SurveyResponse.survey_id == survey_id,
                SurveyResponse.user_id == user_id,
            )
        )
    ) is not None


# --- reads (any feedback access) ---------------------------------------------


@router.get("", response_model=list[SurveySummary])
async def list_surveys(
    competition_id: str,
    current_user: User = Depends(_require_feedback_read()),
    db: AsyncSession = Depends(get_db),
) -> list[SurveySummary]:
    await _guard(db, competition_id)
    is_staff = await user_has_permission(
        db, current_user.id, "feedback_manage", competition_id
    )
    stmt = select(Survey).where(Survey.competition_id == competition_id)
    if not is_staff:
        stmt = stmt.where(Survey.is_open.is_(True))  # competitors see open only
    surveys = (await db.execute(stmt.order_by(Survey.created_at.desc()))).scalars().all()

    out: list[SurveySummary] = []
    for survey in surveys:
        qcount = (
            await db.scalar(
                select(func.count(SurveyQuestion.id)).where(
                    SurveyQuestion.survey_id == survey.id
                )
            )
        ) or 0
        out.append(
            SurveySummary(
                id=survey.id, title=survey.title, description=survey.description,
                is_open=survey.is_open, question_count=qcount,
                response_count=await _response_count(db, survey.id),
                created_at=survey.created_at,
                responded=None if is_staff else await _has_responded(db, survey.id, current_user.id),
            )
        )
    return out


@router.get("/{survey_id}", response_model=SurveyDetail)
async def get_survey(
    competition_id: str,
    survey_id: str,
    current_user: User = Depends(_require_feedback_read()),
    db: AsyncSession = Depends(get_db),
) -> SurveyDetail:
    await _guard(db, competition_id)
    survey = await _survey_or_404(db, competition_id, survey_id)
    is_staff = await user_has_permission(
        db, current_user.id, "feedback_manage", competition_id
    )
    if not survey.is_open and not is_staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found")
    responded = None if is_staff else await _has_responded(db, survey_id, current_user.id)
    return await _detail(db, survey, responded=responded)


# --- survey + question management (feedback_manage) --------------------------


@router.post("", response_model=SurveyDetail, status_code=status.HTTP_201_CREATED)
async def create_survey(
    competition_id: str,
    body: SurveyCreate,
    current_user: User = Depends(require_permission("feedback_manage")),
    db: AsyncSession = Depends(get_db),
) -> SurveyDetail:
    await _guard(db, competition_id)
    survey = Survey(
        competition_id=competition_id, title=body.title, description=body.description,
    )
    db.add(survey)
    await db.commit()
    return await _detail(db, survey, responded=None)


@router.put("/{survey_id}", response_model=SurveyDetail)
async def update_survey(
    competition_id: str,
    survey_id: str,
    body: SurveyUpdate,
    current_user: User = Depends(require_permission("feedback_manage")),
    db: AsyncSession = Depends(get_db),
) -> SurveyDetail:
    await _guard(db, competition_id)
    survey = await _survey_or_404(db, competition_id, survey_id)
    just_opened = body.is_open and not survey.is_open
    survey.title = body.title
    survey.description = body.description
    survey.is_open = body.is_open
    await db.commit()

    # Emit only on the closed→open edge (§3.2) — the trigger for "notify
    # participants a survey is open" rules. A no-op re-save of an open survey
    # doesn't re-fire it.
    if just_opened:
        await event_bus.emit(
            "survey.opened",
            {
                "competition_id": competition_id,
                "survey_id": survey.id,
                "title": survey.title,
                "user_id": current_user.id,
            },
        )
    return await _detail(db, survey, responded=None)


@router.delete("/{survey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_survey(
    competition_id: str,
    survey_id: str,
    current_user: User = Depends(require_permission("feedback_manage")),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _guard(db, competition_id)
    survey = await _survey_or_404(db, competition_id, survey_id)
    await db.delete(survey)
    await db.commit()


@router.post(
    "/{survey_id}/questions", response_model=QuestionOut, status_code=status.HTTP_201_CREATED
)
async def add_question(
    competition_id: str,
    survey_id: str,
    body: QuestionCreate,
    current_user: User = Depends(require_permission("feedback_manage")),
    db: AsyncSession = Depends(get_db),
) -> QuestionOut:
    await _guard(db, competition_id)
    await _survey_or_404(db, competition_id, survey_id)
    next_pos = (
        await db.scalar(
            select(func.max(SurveyQuestion.position)).where(
                SurveyQuestion.survey_id == survey_id
            )
        )
    )
    question = SurveyQuestion(
        competition_id=competition_id, survey_id=survey_id, prompt=body.prompt,
        type=body.type, options=body.options, required=body.required,
        position=(next_pos + 1) if next_pos is not None else 0,
    )
    db.add(question)
    await db.commit()
    return _question_out(question)


@router.put("/{survey_id}/questions/order", response_model=list[QuestionOut])
async def reorder_questions(
    competition_id: str,
    survey_id: str,
    body: ReorderQuestions,
    current_user: User = Depends(require_permission("feedback_manage")),
    db: AsyncSession = Depends(get_db),
) -> list[QuestionOut]:
    await _guard(db, competition_id)
    await _survey_or_404(db, competition_id, survey_id)
    questions = {q.id: q for q in await _questions(db, survey_id)}
    if set(body.question_ids) != set(questions):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reorder must list exactly the survey's questions",
        )
    for position, question_id in enumerate(body.question_ids):
        questions[question_id].position = position
    await db.commit()
    return [_question_out(q) for q in await _questions(db, survey_id)]


@router.put("/{survey_id}/questions/{question_id}", response_model=QuestionOut)
async def update_question(
    competition_id: str,
    survey_id: str,
    question_id: str,
    body: QuestionCreate,
    current_user: User = Depends(require_permission("feedback_manage")),
    db: AsyncSession = Depends(get_db),
) -> QuestionOut:
    await _guard(db, competition_id)
    question = await db.scalar(
        select(SurveyQuestion).where(
            SurveyQuestion.id == question_id,
            SurveyQuestion.survey_id == survey_id,
            SurveyQuestion.competition_id == competition_id,
        )
    )
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    question.prompt = body.prompt
    question.type = body.type
    question.options = body.options
    question.required = body.required
    await db.commit()
    return _question_out(question)


@router.delete(
    "/{survey_id}/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_question(
    competition_id: str,
    survey_id: str,
    question_id: str,
    current_user: User = Depends(require_permission("feedback_manage")),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _guard(db, competition_id)
    question = await db.scalar(
        select(SurveyQuestion).where(
            SurveyQuestion.id == question_id,
            SurveyQuestion.survey_id == survey_id,
            SurveyQuestion.competition_id == competition_id,
        )
    )
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    await db.delete(question)
    await db.commit()


# --- submission (feedback_submit) --------------------------------------------


def _validate_answer(question: SurveyQuestion, value: str) -> None:
    if question.type in _RATING_MAX:
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Question {question.id} expects a number",
            )
        if not 1 <= n <= _RATING_MAX[question.type]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Rating out of range for question {question.id}",
            )
    elif question.type == "multiple_choice" and value not in (question.options or []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Answer not one of the options for question {question.id}",
        )


@router.post("/{survey_id}/responses", status_code=status.HTTP_204_NO_CONTENT)
async def submit_response(
    competition_id: str,
    survey_id: str,
    body: ResponseSubmit,
    current_user: User = Depends(require_permission("feedback_submit")),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _guard(db, competition_id)
    survey = await _survey_or_404(db, competition_id, survey_id)
    if not survey.is_open:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Survey is closed")
    if await _has_responded(db, survey_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You've already responded"
        )

    questions = {q.id: q for q in await _questions(db, survey_id)}
    answers = {a.question_id: a.value for a in body.answers}
    for question in questions.values():
        value = (answers.get(question.id) or "").strip()
        if question.required and not value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Question {question.id} is required",
            )
        if value:
            _validate_answer(question, value)

    response = SurveyResponse(
        competition_id=competition_id, survey_id=survey_id, user_id=current_user.id
    )
    db.add(response)
    await db.flush()
    for question in questions.values():
        value = (answers.get(question.id) or "").strip()
        if value:
            db.add(
                SurveyAnswer(
                    competition_id=competition_id, response_id=response.id,
                    question_id=question.id, value=value,
                )
            )
    await db.commit()

    await event_bus.emit(
        "survey.submitted",
        {
            "competition_id": competition_id,
            "user_id": current_user.id,
            "survey_id": survey_id,
            "response_id": response.id,
        },
    )


# --- results + export (feedback_view_responses) ------------------------------


async def _answers_by_question(
    db: AsyncSession, survey_id: str
) -> dict[str, list[str]]:
    rows = (
        await db.execute(
            select(SurveyAnswer.question_id, SurveyAnswer.value)
            .join(SurveyResponse, SurveyResponse.id == SurveyAnswer.response_id)
            .where(SurveyResponse.survey_id == survey_id)
        )
    ).all()
    grouped: dict[str, list[str]] = {}
    for question_id, value in rows:
        grouped.setdefault(question_id, []).append(value)
    return grouped


@router.get("/{survey_id}/results", response_model=SurveyResults)
async def survey_results(
    competition_id: str,
    survey_id: str,
    current_user: User = Depends(require_permission("feedback_view_responses")),
    db: AsyncSession = Depends(get_db),
) -> SurveyResults:
    await _guard(db, competition_id)
    survey = await _survey_or_404(db, competition_id, survey_id)
    questions = await _questions(db, survey_id)
    grouped = await _answers_by_question(db, survey_id)

    results: list[QuestionResults] = []
    for q in questions:
        values = grouped.get(q.id, [])
        entry = QuestionResults(
            question_id=q.id, prompt=q.prompt, type=q.type, answered=len(values)
        )
        if q.type in _RATING_MAX:
            nums = [int(v) for v in values if v.isdigit()]
            entry.average = round(sum(nums) / len(nums), 2) if nums else None
            counts: dict[str, int] = {}
            for v in values:
                counts[v] = counts.get(v, 0) + 1
            entry.counts = counts
        elif q.type == "multiple_choice":
            counts = {opt: 0 for opt in (q.options or [])}
            for v in values:
                counts[v] = counts.get(v, 0) + 1
            entry.counts = counts
        else:
            entry.texts = values
        results.append(entry)

    return SurveyResults(
        survey_id=survey.id, title=survey.title,
        response_count=await _response_count(db, survey_id), questions=results,
    )


@router.get("/{survey_id}/responses.csv")
async def export_responses_csv(
    competition_id: str,
    survey_id: str,
    current_user: User = Depends(require_permission("feedback_view_responses")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _guard(db, competition_id)
    survey = await _survey_or_404(db, competition_id, survey_id)
    questions = await _questions(db, survey_id)

    responses = (
        await db.execute(
            select(SurveyResponse, User.display_name, User.email)
            .join(User, User.id == SurveyResponse.user_id)
            .where(SurveyResponse.survey_id == survey_id)
            .order_by(SurveyResponse.created_at)
        )
    ).all()
    # answers keyed by (response_id, question_id)
    answer_rows = (
        await db.execute(
            select(SurveyAnswer.response_id, SurveyAnswer.question_id, SurveyAnswer.value)
            .join(SurveyResponse, SurveyResponse.id == SurveyAnswer.response_id)
            .where(SurveyResponse.survey_id == survey_id)
        )
    ).all()
    answers = {(rid, qid): value for rid, qid, value in answer_rows}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["respondent", "email", "submitted_at", *[q.prompt for q in questions]]
    )
    for response, display_name, email in responses:
        writer.writerow(
            [
                display_name,
                email,
                response.created_at.isoformat(),
                *[answers.get((response.id, q.id), "") for q in questions],
            ]
        )

    filename = f"survey-{survey.id}-responses.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
