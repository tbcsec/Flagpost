"""Flag submission model (ARCHITECTURE.md §13.1, §13.2, ROADMAP #11/#12).

Every submission attempt is a row — successes *and* failures (§13.2): failed
attempts feed later challenge-health analytics (Tier 3) and give staff a signal
if a challenge is being brute-forced. The submitted ``value`` is stored so those
analytics have something to look at; it is never compared client-side.

Scoring is recorded on the row itself. The **first** correct submission for a
subject (the team in team-mode, the user in individual-mode) is authoritative:
it carries ``points_awarded = challenge.points`` and ``is_duplicate = False``.
Any later correct submission by the same subject is logged with
``is_duplicate = True`` and ``points_awarded = 0`` — resubmitting a solved flag
never re-awards points or re-emits ``challenge.solved`` (§13.2 idempotency).

"First correct submission is authoritative" is enforced by a partial unique
index, not only by the read-then-write in the submit route. Two concurrent
submissions of the same correct flag each ran their own "has this subject
solved it?" query, both saw nothing, and both inserted an awarded row — so a
competitor who knew a flag could bank N times its points from one burst. The
index makes at most one awarded row per (challenge, subject) a property of the
schema; the route catches the resulting IntegrityError and records the loser as
the duplicate it is.

Tenant-scoped (§6.2, ``CompetitionScopedMixin``); ``team_id`` is denormalized
alongside ``user_id`` so a team's solves are one indexed query without walking
memberships (and it's the unit the scoreboard ranks in team-mode).
"""

from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, and_, func
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin


class Submission(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "submissions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    challenge_id: Mapped[str] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The account that actually submitted (always set, both modes).
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The credited team in team-mode; NULL in individual-mode. SET NULL so a
    # deleted team doesn't erase the historical attempt record.
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # The raw submitted flag text — logged for analytics / brute-force review
    # (§13.2). Compared server-side against the stored hash/pattern, never echoed.
    value: Mapped[str] = mapped_column(String, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Correct, but the subject had already solved this challenge — no re-award.
    is_duplicate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    points_awarded: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # Points deducted from this solve by the multiple-choice wrong-guess penalty
    # (#148): the difference between the base value and what was actually awarded,
    # driven by the subject's incorrect guesses and the competition's
    # ``mc_penalty_pct``. 0 for every non-penalised solve (static/regex, penalty
    # off, or a clean first-guess correct answer). Stored — rather than recomputed
    # — so the dynamic re-value can keep each solver's own penalty when a new solve
    # lowers a dynamic challenge's base value (a single portable UPDATE), instead
    # of collapsing every solver to one value.
    mc_penalty: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


# At most one *awarded* row per (challenge, subject). COALESCE picks the credited
# subject the same way the scoreboard does — the team in team-mode, the user in
# individual-mode, where team_id is NULL. Partial, because duplicate and
# incorrect attempts are deliberately unbounded: every attempt is logged (§13.2).
#
# Expressed with SQLAlchemy constructs rather than raw SQL so each dialect
# renders its own boolean literal; a hand-written `is_correct = 1` would take
# SQLite and be rejected by Postgres.
_AWARDED_ROW = and_(
    Submission.is_correct.is_(True), Submission.is_duplicate.is_(False)
)

Index(
    "uq_submissions_awarded_subject",
    Submission.challenge_id,
    func.coalesce(Submission.team_id, Submission.user_id),
    unique=True,
    sqlite_where=_AWARDED_ROW,
    postgresql_where=_AWARDED_ROW,
)
