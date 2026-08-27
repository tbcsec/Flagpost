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
    # When the retention job may hard-delete this archived competition (#26).
    # Stamped at archive time from the site's archive_auto_delete settings;
    # cleared on unarchive (re-archiving restarts the clock). Null = never —
    # which is also what every competition archived before the feature has, so
    # an upgrade can't retroactively schedule anything for deletion.
    purge_after: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Competition-wide cap on guesses per subject per multiple-choice challenge, to
    # blunt brute-forcing a finite option set. Null = unlimited. New competitions
    # **default to 2** — applied at the API layer (``CompetitionCreate``), not as a
    # column default, so an explicit null (unlimited) isn't clobbered by the
    # SQLAlchemy default-on-None behaviour. Applies only to multiple_choice
    # challenges (static/regex are covered by the submission rate limiter). Not
    # scoped per-challenge by design (owner decision).
    mc_guess_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Anti-brute-force penalty riding alongside the guess limit (#148): each
    # *incorrect* guess on a multiple-choice challenge lowers that challenge's
    # value **for the guessing subject** by this percentage of its base value, so
    # a later correct answer awards less. Linear in the base value, floored at 0
    # (owner decision). 1–100; null = off. Defaults **off** for new competitions
    # (unlike mc_guess_limit's default of 2) so enabling it is an explicit opt-in
    # that never silently changes an existing competition's scoring. Applies only
    # to multiple_choice challenges; competition-wide, not per-challenge (mirrors
    # mc_guess_limit). The per-subject wrong-guess count reuses the reset-aware
    # counter, so a MCGuessReset restores the value along with the attempts.
    mc_penalty_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # Brackets/divisions a competitor self-selects at join (e.g. Students, Open).
    # Null/[] = no brackets. Scoreboard can filter by one.
    brackets: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Max members per team (team-mode). Null = unlimited. Enforced at join.
    max_team_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Challenge instancing (#266, ADR-0036) per-competition policy. Null = fall
    # back to the site defaults. instance_max_alive caps how many instances one
    # subject may hold at once across the competition; instance_lifetime_s is the
    # default session length before TTL reaping (a deployment may override it).
    instance_max_alive: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instance_lifetime_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Paused = gameplay is halted: competitors can't submit flags (staff still
    # can, to test). Distinct from a scoreboard freeze (which only stops the
    # board from moving publicly). Toggled in competition settings.
    paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
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
    # Per-competition rules / code-of-conduct override (issue #57): a rich-text
    # (ProseMirror JSON) document that supersedes the site-wide rules_text for
    # this competition. Null = fall back to the global document. Adding or
    # changing a non-null override deletes the competition's acceptance rows so
    # every participant re-accepts the more specific text (owner decision).
    rules_override: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Display-only flag for the override document (meaningful when
    # rules_override is set): shown at join but never gating. The global
    # document carries its own flag on site_settings.
    rules_display_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Explicit gameplay lifecycle (#221): "not_started" | "running" | "ended".
    # THE gate for competitor access — challenge viewing/submission and the
    # scoreboard are open only while "running" (staff with challenge_edit bypass,
    # to build before and review after). New competitions default "not_started".
    # Both the scheduler (at start_at/end_at) and a judge's manual Start/Stop drive
    # it; a manual action is authoritative and marks the boundary handled via the
    # *_event_fired flags below, so the scheduler won't undo it. Distinct from
    # `paused` (a temporary halt *within* a running competition) and the scoreboard
    # freeze — those are orthogonal axes.
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="not_started", server_default="not_started"
    )
    # Internal dedup for the scheduler's competition.started/ended events — fired
    # once each when the schedule boundary is crossed (or when a judge starts/stops
    # manually), so the scheduler never re-fires or overrides a manual decision.
    started_event_fired: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    ended_event_fired: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
