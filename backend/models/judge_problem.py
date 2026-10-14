"""A programming challenge's problem definition (#447, ADR-0042).

One row per programming challenge. Limits, comparison mode and allowed
languages are all **nullable, meaning "use the default"** — the site defaults
from ``JudgeSettings`` and every enabled language — so an organiser who touches
none of them gets sensible behaviour (VISION principle 5).

Test data is stored as **one object per problem**: a zip in the standard
ICPC/Kattis layout (``data/sample/NNN.in|.ans``, ``data/secret/NNN.in|.ans``).
One object rather than two per test case because:

* the backup's object side-car carries one object per row, so problems ride
  backup, clone and purge with no special-casing;
* it is the interchange format problem-package import (#451) speaks;
* the executor (#448) fetches one object per judging.

``testcases`` is a cached manifest of that zip — ids, the sample flag and sizes,
in order — so listing never has to open it. The zip is rewritten on every
test-case edit, under a row lock so concurrent editors can't lose each other's
changes. File names inside the zip are derived from position on every write, so
they always sort in judging order; the manifest ``id`` is the stable handle.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin

COMPARE_MODES = ("token", "exact", "float")
DEFAULT_FLOAT_TOLERANCE = 1e-6


class JudgeProblem(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "judge_problems"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    challenge_id: Mapped[str] = mapped_column(
        String, ForeignKey("challenges.id", ondelete="CASCADE"),
        nullable=False, unique=True,
    )
    # Null = the site default (JudgeSettings.default_*).
    time_limit_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_limit_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_limit_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # How output is compared with the expected answer. "token" (the default)
    # ignores differences in whitespace and blank lines, the usual contest rule.
    compare_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="token", server_default="token"
    )
    float_tolerance: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Language keys allowed for this problem. Null = every enabled language.
    allowed_languages: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # The test-data zip (null until the first test case is added).
    object_key: Mapped[str | None] = mapped_column(String, nullable=True)
    # Cached manifest of the zip: [{id, sample, input_bytes, answer_bytes}].
    testcases: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)

    @property
    def content_type(self) -> str:
        # Read by the backup importer when it re-stores the object.
        return "application/zip"
