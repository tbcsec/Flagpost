"""Feedback / survey models (ARCHITECTURE.md §13, ROADMAP #22).

A ``Survey`` is a competition-scoped questionnaire (post-competition feedback
is the motivating case, but nothing stops a mid-event one — a competition may
have several). It owns ordered ``SurveyQuestion``s; a competitor submits one
``SurveyResponse`` per survey (per **user** — feedback is an individual opinion,
so responses are per-account even in team mode), and each response holds one
``SurveyAnswer`` per answered question.

Everything is tenant-scoped (§6.2). Answers store their value as text
regardless of question type — a rating as ``"7"``, a multiple-choice pick as
the chosen option, free text as itself — so the one column stays portable
across SQLite/Postgres (ADR-0006) and the question type drives interpretation.
"""

from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin

# Question types (§ROADMAP #22): two rating scales, two free-text lengths, and
# single-select multiple choice.
QUESTION_TYPES = (
    "rating_1_10",
    "rating_1_5",
    "short_text",
    "long_text",
    "multiple_choice",
)


class Survey(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "surveys"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Closed surveys are hidden from competitors and reject submissions; staff
    # open one when it's ready to collect.
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SurveyQuestion(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "survey_questions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    survey_id: Mapped[str] = mapped_column(
        ForeignKey("surveys.id", ondelete="CASCADE"), index=True, nullable=False
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # One of QUESTION_TYPES.
    type: Mapped[str] = mapped_column(String, nullable=False)
    # Choices for multiple_choice (a JSON list of strings); empty otherwise.
    options: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Display order within the survey.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SurveyResponse(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "survey_responses"
    __table_args__ = (
        # One response per user per survey (§ROADMAP #22 invariant).
        UniqueConstraint("survey_id", "user_id", name="uq_survey_response_user"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    survey_id: Mapped[str] = mapped_column(
        ForeignKey("surveys.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )


class SurveyAnswer(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "survey_answers"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    response_id: Mapped[str] = mapped_column(
        ForeignKey("survey_responses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_id: Mapped[str] = mapped_column(
        ForeignKey("survey_questions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The answer as text; interpreted per the question's type.
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
