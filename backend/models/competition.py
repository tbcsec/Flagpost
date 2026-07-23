"""The ``Competition`` entity — the tenancy root (ARCHITECTURE.md §6, §13.1).

Every tenant-scoped table hangs off this via ``competition_id`` (§6.2). The
entity itself is site-wide (it has no parent), so it does not use
``CompetitionScopedMixin``.

The model is defined here in the kernel/auth migration because
``RoleAssignment.competition_id`` references it (§7.5) — the tenancy root has
to exist before anything can be scoped to it. Its HTTP surface (router,
schemas) lands with the competition feature work, not here.

``participation_mode`` is a per-competition setting, not a module toggle
(§11.3): a single deployment may run some competitions team-based and others
solo at the same time. Scoring/scoreboard read it later to decide what they
rank.
"""

from datetime import datetime
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, TimestampMixin, UtcDateTime


def generate_invite_code() -> str:
    """A short random code an organiser shares so competitors can join a
    private competition (§7.5). Mirrors the team invite-code scheme."""
    return token_urlsafe(8)


class Competition(Base, TimestampMixin):
    __tablename__ = "competitions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    registration_opens_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    registration_closes_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # "team" | "individual" (§11.3).
    participation_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="team"
    )
    # "public" | "private". Private by default — a competition isn't visible to
    # competitors until an organiser opens it up.
    visibility: Mapped[str] = mapped_column(
        String, nullable=False, default="private"
    )
    # Shared out-of-band by an organiser so a competitor can join a private
    # competition by code (public competitions can be joined without it, §7.5).
    invite_code: Mapped[str] = mapped_column(
        String, nullable=False, unique=True, default=generate_invite_code
    )
    # Archived = an organiser has closed the competition out. Data is retained;
    # it's just hidden from the switcher/lobby and flagged in the admin list.
    # Reversible (unarchive). Null = active.
    archived_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Competition-wide cap on guesses per subject per multiple-choice challenge, to
    # blunt brute-forcing a finite option set. Null = unlimited. New competitions
    # **default to 2** — applied at the API layer (``CompetitionCreate``), not as a
    # column default, so an explicit null (unlimited) isn't clobbered by the
    # SQLAlchemy default-on-None behaviour. Applies only to multiple_choice
    # challenges (static/regex are covered by the submission rate limiter). Not
    # scoped per-challenge by design (owner decision).
    mc_guess_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Whether solving a challenge prompts the competitor for a 1–5 rating (Phase 9,
    # feedback module). Per-competition so it can be toggled between events.
    challenge_ratings_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Per-competition managed vocabularies (Phase 9): the tag names and ordered
    # difficulty tiers challenges may use. Null/[] = none defined yet. Challenges
    # validate their tags/difficulty against these (a true managed taxonomy).
    challenge_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    difficulty_tiers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Scoreboard freeze (§13, Phase 9): the instant public standings stop moving.
    # Null = live. Reached-and-set → the board is computed as of this time for
    # everyone but staff who explicitly ask for the live view. Can be a future
    # time (freeze scheduled for the final stretch).
    scoreboard_frozen_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True
    )
    # Public spectator scoreboard (Phase 9): opt-in per competition. When on, the
    # board is listed on /public and readable without an account.
    public_scoreboard: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # CTFtime scoreboard feed (Phase 9): opt-in per competition; when on, the
    # ctftime feed URL serves this competition's standings for rating.
    ctftime_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Internal dedup for the scheduler's competition.started/ended events — fired
    # once each when the schedule boundary is crossed.
    started_event_fired: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    ended_event_fired: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
