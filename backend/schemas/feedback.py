"""Pydantic schemas for feedback / surveys (ROADMAP #22)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

QuestionType = Literal[
    "rating_1_10", "rating_1_5", "short_text", "long_text", "multiple_choice"
]


class QuestionCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    type: QuestionType
    options: list[str] = Field(default_factory=list, max_length=20)
    required: bool = True

    @model_validator(mode="after")
    def _options_only_for_choice(self) -> "QuestionCreate":
        if self.type == "multiple_choice":
            non_empty = [o for o in self.options if o.strip()]
            if len(non_empty) < 2:
                raise ValueError("multiple_choice needs at least two options")
            self.options = non_empty
        else:
            self.options = []
        return self


class QuestionOut(BaseModel):
    id: str
    prompt: str
    type: QuestionType
    options: list[str]
    required: bool
    position: int


class SurveyCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class SurveyUpdate(SurveyCreate):
    is_open: bool = False


class SurveySummary(BaseModel):
    id: str
    title: str
    description: str | None
    is_open: bool
    question_count: int
    response_count: int
    created_at: datetime
    # For a competitor: whether they've already responded (so the UI shows
    # "Responded" instead of the form). None for staff views.
    responded: bool | None = None


class SurveyDetail(SurveySummary):
    questions: list[QuestionOut]


class ReorderQuestions(BaseModel):
    question_ids: list[str] = Field(min_length=1)


class AnswerIn(BaseModel):
    question_id: str
    value: str = Field(max_length=5000)


class ResponseSubmit(BaseModel):
    answers: list[AnswerIn] = Field(default_factory=list, max_length=100)


# --- Results (feedback_view_responses) ---------------------------------------


class QuestionResults(BaseModel):
    question_id: str
    prompt: str
    type: QuestionType
    answered: int
    # For ratings: average + a value→count histogram. For multiple_choice: an
    # option→count tally. For text: the list of free-text answers.
    average: float | None = None
    counts: dict[str, int] | None = None
    texts: list[str] | None = None


class SurveyResults(BaseModel):
    survey_id: str
    title: str
    response_count: int
    questions: list[QuestionResults]


# --- Challenge ratings (Phase 9, feedback module extension) -------------------


class ChallengeRatingRequest(BaseModel):
    rating: int = Field(ge=1, le=5)


class ChallengeRatingSummary(BaseModel):
    """Aggregate ratings for one challenge (staff view)."""

    challenge_id: str
    title: str
    average: float
    count: int
