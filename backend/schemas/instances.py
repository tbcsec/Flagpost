"""Pydantic schemas for challenge instancing (#266, ADR-0036).

Three surfaces:

- **Deployment authoring** (staff): the per-challenge ``ChallengeDeployment``
  spec — image/manifest, exposure, ports, guardrails, flag mode.
- **Instance** (competitor + staff): the runtime row, with connection details
  exposed *only* once it is running.
- **Site settings + test-connection** (admin): the singleton provisioner
  config, mirroring the AI module's write-only-secret + staged-check posture.

Models never return an ORM row directly (code conventions); the ``*Out`` models
are ``from_attributes`` and built with ``model_validate``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from models.challenge_instancing import (
    DEPLOYMENT_BACKENDS,
    DEPLOYMENT_EXPOSURES,
    FLAG_MODES,
)

# --- deployment authoring ----------------------------------------------------


class DeploymentUpdate(BaseModel):
    """Upsert the one deployment spec on a challenge (staff authoring)."""

    backend: str = Field(..., description="Provisioner kind")
    image_ref: str | None = None
    manifest: dict[str, Any] | None = None
    exposure: str = "tcp"
    ports: list[int] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    resource_limits: dict[str, Any] | None = None
    lifetime_s: int | None = Field(default=None, ge=60, le=86400)
    per_subject_cap: int = Field(default=1, ge=1, le=100)
    flag_mode: str = "static"
    flag_template: str | None = None

    def validate_shape(self) -> str | None:
        """Return a human error if the spec is internally inconsistent, else
        None. Kept off Pydantic validators so the route can 400 with a clear
        message that names the field."""
        if self.backend not in DEPLOYMENT_BACKENDS:
            return f"backend must be one of {', '.join(DEPLOYMENT_BACKENDS)}"
        if self.exposure not in DEPLOYMENT_EXPOSURES:
            return f"exposure must be one of {', '.join(DEPLOYMENT_EXPOSURES)}"
        if self.flag_mode not in FLAG_MODES:
            return f"flag_mode must be one of {', '.join(FLAG_MODES)}"
        if self.backend in ("docker", "kubernetes") and not self.image_ref:
            return "an image reference is required for the docker/kubernetes backends"
        if self.exposure == "tcp" and not self.ports:
            return "tcp exposure needs at least one container port"
        if any(not (0 < p < 65536) for p in self.ports):
            return "ports must be in 1..65535"
        if self.flag_mode == "unique_per_instance" and not self.flag_template:
            return "unique_per_instance flag mode needs a flag_template"
        return None


class DeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    challenge_id: str
    competition_id: str
    backend: str
    image_ref: str | None
    manifest: dict[str, Any] | None
    exposure: str
    ports: list[int]
    env: dict[str, str]
    resource_limits: dict[str, Any] | None
    lifetime_s: int | None
    per_subject_cap: int
    flag_mode: str
    flag_template: str | None


# --- instances ---------------------------------------------------------------


class InstanceEndpoint(BaseModel):
    kind: str
    host: str | None = None
    port: int | None = None
    url: str | None = None


class InstanceOut(BaseModel):
    """A subject's own instance. ``endpoints`` is populated only while the
    instance is running; ``failure_reason`` only in the failed state."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    challenge_id: str
    status: str
    endpoints: list[dict[str, Any]] = Field(default_factory=list)
    expires_at: datetime | None = None
    started_at: datetime | None = None
    extend_count: int = 0
    failure_reason: str | None = None


class AdminInstanceOut(InstanceOut):
    """The staff ops view adds the subject and backend handle so an operator can
    correlate a row with a live container."""

    competition_id: str
    user_id: str
    team_id: str | None = None
    backend_handle: str | None = None
    created_at: datetime | None = None
    last_seen_at: datetime | None = None
    # Human labels resolved server-side (the ids stay for correlation): the
    # challenge's title and the subject's name (team in team mode, else the
    # requesting user's display name — resolved from the users table, so it
    # covers staff test-launches too, unlike a competitor-roster lookup).
    challenge_title: str | None = None
    subject_label: str | None = None


# --- site settings + test connection -----------------------------------------


class InstanceSettingsOut(BaseModel):
    """Everything the admin infra surface reads. The registry credential is
    never returned — only whether one is stored (``registry_credentials_set``),
    the AI-module write-only-secret posture."""

    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    backend: str
    endpoint_url: str | None
    public_host: str | None
    registry_credentials_set: bool = False
    tcp_port_min: int
    tcp_port_max: int
    default_cpu: float
    default_memory_mb: int
    default_pids: int
    max_concurrent: int
    egress_policy: str


class InstanceSettingsUpdate(BaseModel):
    enabled: bool | None = None
    backend: str | None = None
    endpoint_url: str | None = None
    public_host: str | None = None
    # "" clears the stored credential; omitting leaves it untouched (write-only).
    registry_credentials: str | None = None
    tcp_port_min: int | None = Field(default=None, ge=1, le=65535)
    tcp_port_max: int | None = Field(default=None, ge=1, le=65535)
    default_cpu: float | None = Field(default=None, gt=0, le=64)
    default_memory_mb: int | None = Field(default=None, ge=16, le=131072)
    default_pids: int | None = Field(default=None, ge=16, le=65536)
    max_concurrent: int | None = Field(default=None, ge=1, le=100000)
    egress_policy: str | None = None


class TestConnectionLeg(BaseModel):
    """One staged ``validate()`` leg, surfaced individually so a field
    misconfiguration reads as a labelled, actionable error (ADR-0036 §1)."""

    name: str
    ok: bool
    detail: str


class TestConnectionResult(BaseModel):
    ok: bool
    legs: list[TestConnectionLeg]
