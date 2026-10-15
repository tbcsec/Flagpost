"""Code submissions and their judgings (#448, ADR-0042 §3–§4).

A competitor's code lands as a ``CodeSubmission`` (the source itself is in
object storage — ``Submission.value`` is capped at 500 characters and is the
flag path's column). Judging it is a separate ``Judging`` row, and **that row
is the queue**: no broker. The worker claims a queued judging with one atomic
conditional ``UPDATE … WHERE status = 'queued'`` and checks the row count — the
``invite_links`` ``max_uses`` pattern — which is safe on SQLite and Postgres
alike. A judging that ran has one ``JudgingRun`` per test it executed.

Keeping the judging apart from the submission is what lets #450 rejudge: a
rejudge is a *new* judging of the same code, so history is never rewritten.

Two kinds of submission (#449): ``submit`` is judged against every test and
scored; ``run`` is judged against the examples only and never scored — the
"try it on the samples" button.

The container is opaque while it runs, so the lifecycle is the part the
platform can observe: ``queued → running → done | failed``. ``done`` means a
verdict about the submission was reached; ``failed`` means none could be (the
judge was unavailable through every retry), reported as ``internal_error``.
None of these tables is in the backup: like challenge instances they are
runtime state, and an accepted judging's score already lives in its ordinary
``Submission`` row, which is.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin, UtcDateTime

CODE_SUBMISSION_KINDS = ("submit", "run")

JUDGING_STATUSES = ("queued", "running", "done", "failed")
ACTIVE_JUDGING_STATUSES = ("queued", "running")

JUDGING_TRANSITIONS: dict[str, tuple[str, ...]] = {
    # Claimed by the worker.
    "queued": ("running",),
    # Finished with a verdict; gave up; or reclaimed by the reaper (the worker
    # died, or the judge was unavailable) to be retried.
    "running": ("done", "failed", "queued"),
    "done": (),
    "failed": (),
}


def judging_can_transition(current: str, target: str) -> bool:
    """True when ``current → target`` is a legal step. Re-entering the current
    status is legal (idempotent retries); leaving a terminal one is not."""
    if current == target:
        return True
    return target in JUDGING_TRANSITIONS.get(current, ())


class CodeSubmission(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "code_submissions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    challenge_id: Mapped[str] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The credited team in team mode (as on Submission); SET NULL so a deleted
    # team doesn't erase the history.
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False, default="submit")
    # The language by key, plus its name as it was: a language can be renamed
    # or removed later, and history should still say what was submitted.
    language_key: Mapped[str] = mapped_column(String, nullable=False)
    language_name: Mapped[str] = mapped_column(String, nullable=False)
    source_object_key: Mapped[str] = mapped_column(String, nullable=False)
    source_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # created_at (TimestampMixin) is the submission time — the solve time an
    # accepted judging is backdated to (ADR-0042 §4).


class Judging(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "judgings"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    code_submission_id: Mapped[str] = mapped_column(
        ForeignKey("code_submissions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Denormalized from the submission for the per-challenge and per-subject
    # reads (history, in-flight caps) without a join.
    challenge_id: Mapped[str] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False, default="submit")
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    # One of utils.judge_executor.VERDICTS once done (internal_error if failed).
    verdict: Mapped[str | None] = mapped_column(String, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # When a running judging counts as stuck: its whole time budget plus slack,
    # set at claim. Past it, the reaper reclaims the row.
    deadline_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Claims so far — a judging the judge couldn't complete is retried, but not
    # forever.
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # The compiler's messages (safe to show the competitor: compiling can't
    # read the test data).
    compile_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_memory_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tests_passed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tests_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Why no verdict was reached, for staff. Never shown to the competitor.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The Submission row a scored judging was recorded as (awarded or not).
    submission_id: Mapped[str | None] = mapped_column(
        ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True
    )


# The worker's claim scans queued judgings oldest-first.
Index("ix_judgings_status_created", Judging.status, Judging.created_at)


class JudgingRun(Base, CompetitionScopedMixin):
    """One test of one judging."""

    __tablename__ = "judging_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    judging_id: Mapped[str] = mapped_column(
        ForeignKey("judgings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Position in judging order (examples first), 0-based.
    test_index: Mapped[int] = mapped_column(Integer, nullable=False)
    sample: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    time_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wall_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    memory_kb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The submission's output — examples only (the harness returns none for
    # hidden tests), so the competitor can compare it with the expected output.
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
