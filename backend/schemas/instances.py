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

import ipaddress
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.challenge_instancing import (
    DEPLOYMENT_BACKENDS,
    DEPLOYMENT_EXPOSURES,
    FLAG_MODES,
    FLAG_TEMPLATE_TOKEN,
)

# --- deployment authoring ----------------------------------------------------


# Resource-containment bounds (GHSA-vgrr). A challenge author must not be able
# to disable the operator's fork-bomb/OOM guards: Docker reads a 0 cpu/memory/
# pids as UNLIMITED, so 0 (and negative) is rejected here — absent means "use the
# operator default", never unlimited. Upper bounds mirror the settings caps.
_RESOURCE_MAX: dict[str, float] = {"cpu": 64, "memory_mb": 131072, "pids": 65536}
# One host port is allocated per declared port; without a cap a single deployment
# could claim the whole ephemeral host-port range and starve every other launch.
_MAX_PORTS = 16


def _validate_resource_limits(limits: dict[str, Any] | None) -> str | None:
    if not limits:
        return None
    for key in ("cpu", "memory_mb", "pids"):
        if key not in limits:
            continue
        value = limits[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return (
                f"resource_limits.{key} must be a positive number "
                "(omit it to use the operator default; 0 would mean unlimited)"
            )
        if value > _RESOURCE_MAX[key]:
            return f"resource_limits.{key} exceeds the maximum {int(_RESOURCE_MAX[key])}"
    return None


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
        if len(self.ports) > _MAX_PORTS:
            return f"at most {_MAX_PORTS} ports may be exposed"
        limits_error = _validate_resource_limits(self.resource_limits)
        if limits_error:
            return limits_error
        if self.flag_mode == "unique_per_instance":
            if not self.flag_template:
                return "unique_per_instance flag mode needs a flag_template"
            if FLAG_TEMPLATE_TOKEN not in self.flag_template:
                return (
                    f"a unique flag_template must contain {FLAG_TEMPLATE_TOKEN} "
                    "so each instance gets a distinct flag"
                )
            # A shared-static endpoint is one fixed container the whole event
            # connects to — it can't hold a per-subject flag, so the combination
            # would render a flag that never reaches a container and grade as
            # unsolvable. Reject at authoring rather than silently at grading.
            if self.backend == "shared-static":
                return "unique_per_instance flags require a per-instance backend, not shared-static"
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

# Kubernetes object-name shapes (#320). A namespace is an RFC 1123 *label*;
# IngressClass/Secret names are RFC 1123 *subdomains* — dot-separated labels
# (the regex is per-label; the validator caps total length at 253).
_RFC1123_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
_RFC1123_SUBDOMAIN = re.compile(
    r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*"
)


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
    chal_base_domain: str | None
    spawn_rate_limit: int
    spawn_rate_window_seconds: int
    # Kubernetes kind (#320). The bearer token is never returned — only whether
    # one is stored, the registry-credential posture.
    k8s_namespace: str
    k8s_bearer_token_set: bool = False
    k8s_ca_cert: str | None
    k8s_ingress_class: str | None
    k8s_image_pull_secret: str | None
    k8s_cluster_cidr: str | None


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
    # HTTP routing base domain (#319). "" clears it; omitting leaves it untouched.
    chal_base_domain: str | None = None
    # Spawn throttle (#319): 0 disables. Window in seconds.
    spawn_rate_limit: int | None = Field(default=None, ge=0, le=100000)
    spawn_rate_window_seconds: int | None = Field(default=None, ge=1, le=86400)
    # Kubernetes kind (#320). The bearer token is write-only: "" clears it,
    # omitting leaves it untouched (the registry_credentials contract). The
    # other optional fields also clear on "".
    k8s_namespace: str | None = None
    k8s_bearer_token: str | None = None
    k8s_ca_cert: str | None = None
    k8s_ingress_class: str | None = None
    k8s_image_pull_secret: str | None = None
    k8s_cluster_cidr: str | None = None

    @field_validator("k8s_bearer_token")
    @classmethod
    def _strip_bearer_token(cls, v: str | None) -> str | None:
        """Strip surrounding whitespace so a token pasted with a trailing
        newline (the shape of ``kubectl create token …``) isn't stored broken
        and invisible — it is write-only, so an operator can't see the mangled
        value to diagnose it. A now-empty result clears the stored token, and
        because the enable-invariant keys on "a token is present", a
        whitespace-only paste no longer counts as configured."""
        if v is None:
            return None
        return v.strip()

    @field_validator("chal_base_domain")
    @classmethod
    def _normalise_base_domain(cls, v: str | None) -> str | None:
        """Accept a bare, lowercased domain (``chal.example.org``) or ``""`` to
        clear. Rejects a scheme/path/port/whitespace so an operator paste like
        ``https://chal.example.org/`` fails at the boundary, not at launch."""
        if v is None:
            return None
        v = v.strip().lower()
        if v and (
            any(c.isspace() for c in v)
            or "/" in v
            or ":" in v
            or v.startswith(".")
            or v.endswith(".")
            or ".." in v
        ):
            raise ValueError(
                "chal_base_domain must be a bare domain like 'chal.example.org' "
                "(no scheme, path, or port)"
            )
        return v

    @field_validator("k8s_namespace")
    @classmethod
    def _validate_namespace(cls, v: str | None) -> str | None:
        """A Kubernetes namespace is an RFC 1123 *label* (no dots). Unlike the
        clearable fields there is no empty form — the column is non-null with a
        default — so "" is rejected rather than treated as "clear". Uppercase
        is rejected, not coerced: the value names an existing cluster object,
        and lowercasing a paste would silently point at a different one."""
        if v is None:
            return None
        v = v.strip()
        if not _RFC1123_LABEL.fullmatch(v):
            raise ValueError(
                "k8s_namespace must be a lowercase RFC 1123 label "
                "(letters/digits/hyphens, at most 63 chars)"
            )
        return v

    @field_validator("k8s_ca_cert")
    @classmethod
    def _validate_ca_cert(cls, v: str | None) -> str | None:
        """"" clears. A real value must look like a PEM certificate bundle, so
        a pasted token/kubeconfig/base64 blob fails at the boundary with a
        message that names the fix, not at the first TLS handshake."""
        if v is None:
            return None
        v = v.strip()
        if v and "-----BEGIN CERTIFICATE-----" not in v:
            raise ValueError(
                "k8s_ca_cert must be a PEM certificate bundle "
                "(-----BEGIN CERTIFICATE-----…)"
            )
        return v

    @field_validator("k8s_ingress_class", "k8s_image_pull_secret")
    @classmethod
    def _validate_k8s_name(cls, v: str | None) -> str | None:
        """"" clears. A real value must be an RFC 1123 subdomain-shaped
        Kubernetes object name (IngressClass / Secret names both are).
        Uppercase is rejected, not coerced — see ``_validate_namespace``."""
        if v is None:
            return None
        v = v.strip()
        if v and (len(v) > 253 or not _RFC1123_SUBDOMAIN.fullmatch(v)):
            raise ValueError(
                "must be a Kubernetes object name "
                "(lowercase letters/digits/hyphens/dots, at most 253 chars)"
            )
        return v

    @field_validator("k8s_cluster_cidr")
    @classmethod
    def _validate_cluster_cidr(cls, v: str | None) -> str | None:
        """"" clears. A real value is one or more comma-separated CIDRs (a
        cluster typically has two — the pod range and the service range, e.g.
        "10.42.0.0/16,10.43.0.0/16"). Each part must parse; the stored form is
        the normalised network addresses, so NetworkPolicy composition can use
        them verbatim."""
        if v is None:
            return None
        v = v.strip()
        if not v:
            return ""
        normalised: list[str] = []
        for part in v.split(","):
            part = part.strip()
            try:
                normalised.append(str(ipaddress.ip_network(part, strict=False)))
            except ValueError:
                raise ValueError(
                    f"k8s_cluster_cidr: {part!r} is not a CIDR — use comma-"
                    'separated ranges like "10.42.0.0/16,10.43.0.0/16"'
                ) from None
        return ",".join(normalised)


class TestConnectionLeg(BaseModel):
    """One staged ``validate()`` leg, surfaced individually so a field
    misconfiguration reads as a labelled, actionable error (ADR-0036 §1)."""

    name: str
    ok: bool
    detail: str


class TestConnectionResult(BaseModel):
    ok: bool
    legs: list[TestConnectionLeg]
