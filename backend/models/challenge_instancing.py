"""Challenge instancing (#266, ADR-0036): deployment specs and live instances.

Two tables, both tenant-scoped (§6.2):

``ChallengeDeployment`` is *authoring content* — at most one per challenge,
describing what to run (image/manifest), how it is exposed, its guardrails and
its flag mode. It rides the backup (ADR-0016) and the ctfcli mapping.

``ChallengeInstance`` is *runtime state* — one row per provisioned copy, and
the row itself is the provisioning job (ADR-0036 §2): its ``status`` walks the
lifecycle state machine below on the background lane, so there is no separate
queue to keep consistent with the DB. Instances are never exported.

Subject convention mirrors ``Submission``: ``user_id`` is always the
requesting account; ``team_id`` is the credited team in team-mode and NULL in
individual-mode, so ``COALESCE(team_id, user_id)`` is the subject — the same
expression the scoreboard and the awarded-solve index use.

Flag material (``flag_hash``/``flag_salt`` for ``unique_per_instance`` mode)
mirrors the static-flag columns on ``Challenge`` and is never exposed by any
schema; the plaintext exists only inside the instance (ADR-0036 §3).
"""

from uuid import uuid4

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin, UtcDateTime
from datetime import datetime

# --- deployment spec vocab ---------------------------------------------------

# Provisioner kinds (ADR-0036 §1). A new backend is a new kind, not a fork.
DEPLOYMENT_BACKENDS = ("docker", "kubernetes", "shared-static")
# How competitors reach an instance. "none" covers challenges whose instance
# is reached indirectly (e.g. a bot visits it) or that only exist to hold a
# unique flag.
DEPLOYMENT_EXPOSURES = ("tcp", "http", "none")
# "static" = the challenge's ordinary flag config applies (static/regex/MCQ);
# "unique_per_instance" = render flag_template at provision time (ADR-0036 §3).
FLAG_MODES = ("static", "unique_per_instance")

# --- instance lifecycle ------------------------------------------------------

INSTANCE_STATUSES = (
    "requested",     # row created; provisioning not yet picked up
    "provisioning",  # background task is talking to the backend
    "running",       # live; endpoints valid
    "expiring",      # TTL reached / teardown requested; destroy in flight
    "destroyed",     # terminal, clean
    "failed",        # terminal, with failure_reason
)

# Statuses that count against caps and can be resolved for grading.
INSTANCE_ACTIVE_STATUSES = ("requested", "provisioning", "running", "expiring")

# The allowed transitions (ADR-0036 §2). Everything else is a bug; the service
# layer refuses it and the transition stays idempotent (a no-op re-entry of the
# current status is always allowed).
INSTANCE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "requested": ("provisioning", "failed", "destroyed"),
    "provisioning": ("running", "failed", "expiring"),
    "running": ("expiring", "failed"),
    "expiring": ("destroyed", "failed"),
    "destroyed": (),
    "failed": (),
}


def instance_can_transition(current: str, target: str) -> bool:
    """True when ``current → target`` is a legal lifecycle step.

    Re-entering the current status is legal (idempotence for retried
    background work); leaving a terminal status is not.
    """
    if current == target:
        return True
    return target in INSTANCE_TRANSITIONS.get(current, ())


class ChallengeDeployment(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "challenge_deployments"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    # One spec per challenge — the editor edits in place rather than stacking
    # variants (unique, not just indexed).
    challenge_id: Mapped[str] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # Provisioner kind (DEPLOYMENT_BACKENDS). Site settings configure one live
    # orchestrating backend, but "shared-static" is inherently per-challenge —
    # a fixed endpoint with no lifecycle — so the spec carries its own kind.
    backend: Mapped[str] = mapped_column(String, nullable=False)
    # Container image reference for docker/kubernetes kinds.
    image_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    # Kind-specific extra config: a k8s manifest fragment, or the fixed
    # endpoints of a shared-static deployment. Opaque JSON, validated by the
    # provisioner kind at authoring time.
    manifest: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    exposure: Mapped[str] = mapped_column(
        String, nullable=False, default="tcp", server_default="tcp"
    )
    # Container ports to expose, e.g. [1337]. JSON list for portability.
    ports: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Non-secret environment for the instance. The unique flag is injected by
    # the provisioner at create time and never stored here.
    env: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Per-challenge overrides of the site-level default limits
    # (cpu/mem/pids); null = defaults apply.
    resource_limits: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Instance lifetime override in seconds; null = the competition's session
    # length applies.
    lifetime_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    per_subject_cap: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    flag_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="static", server_default="static"
    )
    # Template rendered at provision time in unique mode, e.g.
    # "flag{prefix-<random>}". Null in static mode.
    flag_template: Mapped[str | None] = mapped_column(String, nullable=True)


class ChallengeInstance(Base, CompetitionScopedMixin, TimestampMixin):
    __tablename__ = "challenge_instances"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid4())
    )
    challenge_id: Mapped[str] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The spec this instance was provisioned from. CASCADE: deleting the spec
    # (or its challenge) reaps the rows; the reaper handles the containers.
    deployment_id: Mapped[str] = mapped_column(
        ForeignKey("challenge_deployments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # The account that requested the instance (always set, both modes).
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The credited team in team-mode; NULL in individual-mode. SET NULL so a
    # deleted team leaves the row for the orphan reaper instead of vanishing a
    # live container's record.
    team_id: Mapped[str | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="requested", server_default="requested"
    )
    # Backend-native identifier (container id, k8s resource name). Null until
    # provisioning reaches the backend.
    backend_handle: Mapped[str | None] = mapped_column(String, nullable=True)
    # Connection details as shown to the subject:
    # [{"kind": "tcp", "host": ..., "port": ...}, {"kind": "http", "url": ...}]
    endpoints: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Unique-mode flag material — same shape and posture as Challenge's static
    # flag columns (hashed at rest, never exposed). Null in static mode.
    flag_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    flag_salt: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    destroyed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Last successful health/status observation (reaper + ops view).
    last_seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # How many extensions the subject has used (per-competition policy).
    extend_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)


# Fast path for "the subject's active instance(s) of this challenge" — the
# grading resolution and the cap check both hit it. Partial (active rows only)
# and deliberately NOT unique: per_subject_cap may allow more than one, so the
# cap is enforced in the service transaction, not the schema. COALESCE picks
# the credited subject exactly as the awarded-solve index does. Expressed with
# SQLAlchemy constructs so each dialect renders its own literals (the pages
# migration's boolean lesson, generalised).
_ACTIVE_ROW = ChallengeInstance.status.in_(INSTANCE_ACTIVE_STATUSES)

Index(
    "ix_challenge_instances_active_subject",
    ChallengeInstance.challenge_id,
    func.coalesce(ChallengeInstance.team_id, ChallengeInstance.user_id),
    sqlite_where=_ACTIVE_ROW,
    postgresql_where=_ACTIVE_ROW,
)
