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
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from db import Base, CompetitionScopedMixin, TimestampMixin, UtcDateTime
from datetime import datetime

from utils.crypto import EncryptedString

# Site-level provisioner config is a singleton, like ai_settings / site_settings.
INSTANCE_SETTINGS_ID = "instances"
# Orchestrating backends the *site* configures. "shared-static" is inherently
# per-deployment (fixed endpoints in the challenge's manifest), so it is not a
# site backend — only these run a lifecycle.
SITE_BACKENDS = ("docker", "kubernetes")
DEFAULT_TCP_PORT_MIN = 30000
DEFAULT_TCP_PORT_MAX = 32767
DEFAULT_MAX_CONCURRENT = 100

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
# The placeholder a unique-mode flag_template must contain; the provisioner
# substitutes a fresh random token for it at provision time so every instance
# gets a distinct flag. Authoring validation requires it to be present.
FLAG_TEMPLATE_TOKEN = "<random>"

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


class InstanceSettings(Base, TimestampMixin):
    """Site-level provisioner configuration (ADR-0036 §5), a singleton like
    ``ai_settings``. Site-wide, so **no** ``CompetitionScopedMixin``.

    Ships unconfigured and disabled: the instances module is inert until an
    operator points it at a container-runtime endpoint and enables it, on top
    of the per-competition module toggle — the AI-module posture (ADR-0023).
    Nothing here is environment-portable (a Docker endpoint is specific to the
    host), so this row is deliberately excluded from the backup export, like
    the operator's other infrastructure credentials.
    """

    __tablename__ = "instance_settings"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=INSTANCE_SETTINGS_ID
    )
    # Master switch. Off until an operator configures + enables a backend; no
    # provisioning happens while false. Enabling is refused at the API unless
    # backend + endpoint are set, so "enabled but unconfigured" isn't reachable
    # (the AiSettings / identity-provider posture).
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Orchestrating backend kind (SITE_BACKENDS).
    backend: Mapped[str] = mapped_column(
        String, nullable=False, default="docker", server_default="docker"
    )
    # The container-runtime API endpoint — **always** a least-privilege socket
    # proxy (ADR-0036 §1), never a raw Docker socket. A trusted operator setting
    # (the SMTP-host / OIDC-issuer class), so not run through the ADR-0013 SSRF
    # blocklist: it is expected to point at a private address (the sidecar, or a
    # challenge host on a private subnet).
    endpoint_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Public hostname competitors connect to (TCP host / HTTP subdomain base).
    public_host: Mapped[str | None] = mapped_column(String, nullable=True)
    # Registry auth for private challenge images. Presented to the runtime, so
    # encrypted at rest not hashed (ADR-0020), write-only over the API, dropped
    # from backup — and deferred, so re-entering a rotated credential on the
    # settings page can't 500 on a decrypt mismatch (the AiSettings.api_key
    # lesson).
    registry_credentials: Mapped[str | None] = mapped_column(
        EncryptedString, nullable=True, deferred=True
    )
    # TCP exposure port range on the instance host (inclusive).
    tcp_port_min: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_TCP_PORT_MIN,
        server_default=str(DEFAULT_TCP_PORT_MIN),
    )
    tcp_port_max: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_TCP_PORT_MAX,
        server_default=str(DEFAULT_TCP_PORT_MAX),
    )
    # Default per-instance resource limits, overridable per deployment.
    # Fractional CPUs (0.5) are the common case, so Float; the generic type
    # carries across SQLite/Postgres.
    default_cpu: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1"
    )
    default_memory_mb: Mapped[int] = mapped_column(
        Integer, nullable=False, default=256, server_default="256"
    )
    default_pids: Mapped[int] = mapped_column(
        Integer, nullable=False, default=256, server_default="256"
    )
    # Global ceiling on simultaneously-live instances across all competitions —
    # the compute-exhaustion backstop (ADR-0036 §5).
    max_concurrent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_MAX_CONCURRENT,
        server_default=str(DEFAULT_MAX_CONCURRENT),
    )
    # Instance egress policy: "deny" (default — no outbound from instances) or
    # "allow" (per-competition opt-in for challenges that need the internet).
    egress_policy: Mapped[str] = mapped_column(
        String, nullable=False, default="deny", server_default="deny"
    )


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
