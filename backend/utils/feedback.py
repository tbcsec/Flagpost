"""Survey (feedback) reads shared beyond the feedback router (§11.3 optional
module, #22).

Extracted from ``routers/feedback`` so the results aggregation — question
tallies, rating averages, free-text lists — and the small survey queries it
builds on are callable outside an HTTP request (the assistant's feedback tool
reuses them) rather than duplicated. This module only *reads*: the module-enabled
gate and the ``feedback_view_responses`` permission stay at the route and are
re-applied by any non-route caller.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.feedback import Survey, SurveyAnswer, SurveyQuestion, SurveyResponse
from schemas.feedback import QuestionResults, SurveyResults

# Rating question types and their scale ceiling — shared by submit-time
# validation (the router) and results aggregation (below).
RATING_MAX = {"rating_1_10": 10, "rating_1_5": 5}


async def survey_questions(db: AsyncSession, survey_id: str) -> list[SurveyQuestion]:
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


async def survey_response_count(db: AsyncSession, survey_id: str) -> int:
    return (
        await db.scalar(
            select(func.count(SurveyResponse.id)).where(
                SurveyResponse.survey_id == survey_id
            )
        )
    ) or 0


async def answers_by_question(
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


async def survey_results(
    db: AsyncSession, competition_id: str, survey_id: str
) -> SurveyResults | None:
    """Aggregate results for one survey (rating averages + counts, choice
    counts, free-text lists), or ``None`` if the survey doesn't exist in this
    competition. The output is competition-scoped by the survey lookup."""
    survey = await db.scalar(
        select(Survey).where(
            Survey.id == survey_id, Survey.competition_id == competition_id
        )
    )
    if survey is None:
        return None

    questions = await survey_questions(db, survey_id)
    grouped = await answers_by_question(db, survey_id)

    results: list[QuestionResults] = []
    for q in questions:
        values = grouped.get(q.id, [])
        entry = QuestionResults(
            question_id=q.id, prompt=q.prompt, type=q.type, answered=len(values)
        )
        if q.type in RATING_MAX:
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
        survey_id=survey.id,
        title=survey.title,
        response_count=await survey_response_count(db, survey_id),
        questions=results,
    )
