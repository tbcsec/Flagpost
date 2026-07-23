"""Challenge domain models: ``Category`` and ``Challenge`` (§13.1, ROADMAP #8/#9).

Both are tenant-scoped (§6.2). Flag material (``flag_hash``/``flag_salt`` for
static, ``flag_regex`` for regex) is **never** exposed by any schema — admin
responses carry only a ``has_flag`` boolean (§13.2). ``state`` is
draft|published for Tier 1; Tier 2's lifecycle (ROADMAP #17) inserts "review"
between them without a rename.

``description`` is a TipTap/ProseMirror document stored as JSON (§2 rich-text
choice) — the editor's native format, portable across SQLite/Postgres via the
generic JSON type (ADR-0006).
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin, UtcDateTime


class Category(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint(
            "competition_id", "name", name="uq_category_name_per_competition"
        ),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)


class Challenge(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "challenges"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    # TipTap document (JSON). Empty dict = no description yet.
    description: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # SET NULL: deleting a category uncategorizes its challenges, never deletes them.
    category_id: Mapped[str | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # For static scoring this is the fixed award; for dynamic it's the *initial*
    # value a challenge is worth before anyone solves it.
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # "static" (fixed points) | "dynamic" (value decays toward min_points as more
    # subjects solve it — the CTFd model; every solver converges to the current
    # value). min_points/decay are required + only meaningful when dynamic.
    scoring_type: Mapped[str] = mapped_column(
        String, nullable=False, default="static", server_default="static"
    )
    min_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decay: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # "draft" | "published" (Tier 2 adds "review").
    state: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    # Scheduled/waved release (Phase 9): a published challenge with a future
    # release_at stays hidden from competitors until then (staff always see it).
    # Null = released as soon as it's published.
    release_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Unlock chains (Phase 9): challenge ids (same competition) a subject must
    # solve before this one unlocks. Null/[] = no prerequisites. Shown-locked:
    # a competitor sees a locked challenge but can't open/submit it until met.
    prerequisites: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Metadata (Phase 9), validated against the competition's managed vocab: a
    # subset of its tag names, and one of its difficulty tiers (or null).
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- Flag config (§13.2) — the secret parts are never serialized ---
    # "static" | "regex" | "multiple_choice"
    flag_type: Mapped[str] = mapped_column(String, nullable=False, default="static")
    case_insensitive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    flag_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    flag_salt: Mapped[str | None] = mapped_column(String, nullable=True)
    flag_regex: Mapped[str | None] = mapped_column(String, nullable=True)
    # Multiple-choice options shown to the competitor (public — the correct one is
    # NOT marked here; it's stored hashed in flag_hash like a static flag, so the
    # answer never leaves the server). Non-null only for flag_type "multiple_choice".
    choices: Mapped[list | None] = mapped_column(JSON, nullable=True)

    @property
    def has_flag(self) -> bool:
        if self.flag_type == "regex":
            return self.flag_regex is not None
        if self.flag_type == "multiple_choice":
            return self.flag_hash is not None and bool(self.choices)
        return self.flag_hash is not None
