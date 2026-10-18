"""Provisioner contract for challenge instancing (#266, ADR-0036 §1).

A *provisioner* turns a challenge's deployment spec into a running, isolated
instance for a subject, and back. Backends register by **kind** — the
identity-provider pattern (ADR-0021): a new backend is a new kind, not a
fork. Phase 0 ships the contract, the registry, and the trivial
``shared-static`` kind (fixed endpoints, no lifecycle) that development and
tests run against; the ``docker`` kind (via a least-privilege socket proxy)
follows in Phase 1 and ``kubernetes`` in Phase 3.

``validate()`` is a first-class part of the contract, not a ping (ADR-0036
§1): it returns an *ordered* list of named check legs, each pass/fail with
human-readable detail, and the admin "Test connection" UI renders the legs
individually so a field misconfiguration surfaces as a labelled, actionable
error rather than a dead connection string on event day.

This module is deliberately free of module/router registration: nothing here
is user-visible until the instances module ships (main is deployed to the
public demo on every merge).
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

# --- per-instance resource bounds (GHSA-vgrr) --------------------------------

# The one source of truth for cpu/memory/pids bounds: the deployment-authoring
# schema, the operator-default settings schema, and every provisioner's final
# clamp all read these. Docker reads a 0 cpu/memory/pids as UNLIMITED, so no
# value may reach a runtime as 0 — including one that int()-truncates there
# (0.5 pids, or 1e-10 cpu → NanoCpus 0). cpu's floor is Docker's own minimum
# (0.01 CPU); memory/pids floors match the operator settings'. memory_mb and
# pids are whole numbers.
RESOURCE_MIN: dict[str, float] = {"cpu": 0.01, "memory_mb": 16, "pids": 16}
RESOURCE_MAX: dict[str, float] = {"cpu": 64, "memory_mb": 131072, "pids": 65536}
INTEGER_RESOURCES = frozenset({"memory_mb", "pids"})


def _finite_number(value: Any) -> int | float | None:
    """``value`` if it is a usable number, else None. bool is an int subclass
    but never a limit; an int is always finite (and may exceed float range, so
    it is not passed to ``math.isfinite``, which would overflow)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _clamp(key: str, value: int | float) -> int | float:
    """A finite ``value`` clamped into ``[RESOURCE_MIN, RESOURCE_MAX]`` for
    ``key``; memory/pids truncated to an int (never below the integer floor)."""
    value = min(max(value, RESOURCE_MIN[key]), RESOURCE_MAX[key])
    return int(value) if key in INTEGER_RESOURCES else value


def resource_limit(
    limits: dict[str, Any] | None, key: str, default: float
) -> float | int:
    """The value a runtime limit is actually set to: the deployment's override
    for ``key`` when it is a finite number, else the operator ``default`` —
    clamped into ``[RESOURCE_MIN, RESOURCE_MAX]`` (an int for memory/pids).

    Defence in depth behind the authoring schema (GHSA-vgrr): the lifecycle
    service passes the stored ``resource_limits`` through raw and
    ``validate_shape`` is not re-run at provision time, so a row written before
    the floors existed can still carry 0, a fraction or NaN. Whatever arrives,
    the runtime never sees a value that means "unlimited"."""
    value = _finite_number((limits or {}).get(key, default))
    if value is None:
        value = _finite_number(default)
    if value is None:
        value = RESOURCE_MIN[key]
    value = _clamp(key, value)
    return value if key in INTEGER_RESOURCES else float(value)


def normalise_resource_limits(limits: Any) -> Any:
    """Bring a stored ``resource_limits`` mapping inside today's bounds by the
    same rules as :func:`resource_limit`: a finite number is clamped (and made
    an int for memory/pids); a non-finite, non-numeric or bool value is dropped,
    so the operator default applies — exactly what the provisioners would have
    run. Other keys pass through, and a non-mapping is returned untouched for
    the caller's validation to reject.

    For restoring rows an earlier release accepted (GHSA-vgrr tightened the
    authoring bounds after v1.7.x): the backup import cleans rather than
    refuses them, so an old backup still restores. Interactive authoring and
    the ctfcli import keep *rejecting* such values — there the author is
    present to fix them."""
    if not isinstance(limits, dict):
        return limits
    out = {k: v for k, v in limits.items() if k not in RESOURCE_MIN}
    for key in RESOURCE_MIN:
        if key not in limits:
            continue
        value = _finite_number(limits[key])
        if value is not None:
            out[key] = _clamp(key, value)
    return out


@dataclass(frozen=True)
class CheckResult:
    """One leg of a staged ``validate()`` run.

    ``name`` is a stable machine key (the UI translates it); ``detail`` is
    operator-facing English with the specifics ("port 30001 on
    chal.example.org is not reachable"), never a bare boolean.
    """

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ProvisionSpec:
    """Everything a backend needs to create one instance.

    Assembled by the lifecycle service (Phase 1) from the challenge's
    ``ChallengeDeployment`` row, the competition's session policy, and — in
    unique-flag mode — the rendered plaintext flag, which exists only in
    memory on its way into the instance (ADR-0036 §3).
    """

    # The instance row's id — names/labels the backend resource so the row and
    # the container map 1:1 (and the orphan reaper can diff by label).
    instance_id: str
    deployment_id: str
    challenge_id: str
    competition_id: str
    image_ref: str | None
    manifest: dict[str, Any] | None
    exposure: str
    # Container ports the image listens on, e.g. [1337].
    ports: list[int]
    env: dict[str, str]
    resource_limits: dict[str, Any] | None
    lifetime_s: int
    # The credited subject key (team id in team mode, user id otherwise) —
    # used for naming/labelling backend resources, never for auth decisions.
    subject_key: str
    # Container-port → host-port bindings the lifecycle service allocated from
    # the configured range (ADR-0036 §4). Empty for exposure="none".
    host_ports: dict[int, int] = field(default_factory=dict)
    # HTTP exposure only (#319): the per-instance subdomain token allocated in the
    # admission transaction. The backend combines it with its base domain into the
    # routing label + the `https://<subdomain>.<base>` URL. None for TCP/none.
    subdomain: str | None = None
    # Plaintext unique flag to inject, or None in static mode. Never stored.
    flag_plaintext: str | None = None
    # Env var the unique flag is injected under when flag_plaintext is set.
    flag_env: str = "FLAG"


class ProvisionerError(Exception):
    """Base class for backend failures the lifecycle service can surface."""


class UnknownProvisionerKind(ProvisionerError):
    def __init__(self, kind: str) -> None:
        super().__init__(f"Unknown provisioner kind: {kind!r}")
        self.kind = kind


class Provisioner(ABC):
    """The backend contract (ADR-0036 §1). All methods are async.

    ``handle`` is the backend-native identifier (container id, k8s resource
    name, or a synthetic token for static kinds) — persisted on the instance
    row as ``backend_handle`` and treated as opaque everywhere else.

    Implementations are constructed per use with their kind-specific
    configuration (site provisioner settings, or the deployment's manifest
    for ``shared-static``); the registry stores classes, not instances.
    """

    #: Registry key; must match a value in models DEPLOYMENT_BACKENDS.
    kind: ClassVar[str]

    @abstractmethod
    async def create(self, spec: ProvisionSpec) -> str:
        """Provision an instance and return its backend handle."""

    @abstractmethod
    async def status(self, handle: str) -> str:
        """The backend's view of the instance: ``running`` | ``stopped`` |
        ``unknown``. The lifecycle service maps this onto the instance state
        machine; backends never write DB state themselves."""

    @abstractmethod
    async def endpoints(self, handle: str) -> list[dict[str, Any]]:
        """Connection details as stored on the row / shown to the subject:
        ``[{"kind": "tcp", "host": ..., "port": ...}, {"kind": "http",
        "url": ...}]``."""

    @abstractmethod
    async def destroy(self, handle: str) -> None:
        """Tear the instance down. Must be idempotent: destroying an
        already-gone handle is a no-op, not an error (the reaper retries)."""

    @abstractmethod
    async def list(self) -> list[str]:
        """Handles of every instance this backend currently holds that was
        created by Flagpost — the orphan reaper diffs this against the
        instance rows."""

    @abstractmethod
    async def validate(self) -> list[CheckResult]:
        """The staged "Test connection" run. Ordered; later legs may be
        skipped when an earlier one fails, but every returned leg must carry
        actionable ``detail``."""

    # Per-instance network isolation cleanup (GHSA-vgrr). Only the docker kind
    # creates a network object per instance, so the orphan-network sweep is a
    # backend capability, not part of the core contract: the default is "no such
    # networks", which the reaper reads as nothing to sweep. A backend that does
    # (docker) overrides both.
    async def list_orphan_networks(self) -> set[str]:
        """Names of backend-managed per-instance networks with no attached
        workload — orphans the reaper may remove. Default: none."""
        return set()

    async def remove_network(self, name: str) -> None:
        """Remove a backend-managed per-instance network by name. Default no-op."""
        return None


# --- kind registry -----------------------------------------------------------

_KINDS: dict[str, type[Provisioner]] = {}


def register_provisioner(cls: type[Provisioner]) -> type[Provisioner]:
    """Class decorator: register a backend by its ``kind``."""
    _KINDS[cls.kind] = cls
    return cls


def provisioner_kind(kind: str) -> type[Provisioner]:
    try:
        return _KINDS[kind]
    except KeyError:
        raise UnknownProvisionerKind(kind) from None


def provisioner_kinds() -> tuple[str, ...]:
    return tuple(sorted(_KINDS))


# --- shared-static: fixed endpoints, no lifecycle (ADR-0036 §1) --------------


@register_provisioner
class SharedStaticProvisioner(Provisioner):
    """A deployment whose "instance" is one always-on shared endpoint.

    Covers stateless challenges (crypto, some web) where per-subject
    isolation adds nothing, and doubles as the zero-infra kind development
    and tests run against. Configuration lives in the deployment's
    ``manifest``: ``{"endpoints": [{"kind": "tcp", "host": ..., "port":
    ...}]}``. There is nothing to start or stop, so every subject shares the
    synthetic handle and ``destroy`` is a no-op.
    """

    kind: ClassVar[str] = "shared-static"

    _HANDLE = "shared-static"

    def __init__(self, manifest: dict[str, Any] | None) -> None:
        self._manifest = manifest or {}

    @property
    def _configured_endpoints(self) -> list[dict[str, Any]]:
        endpoints = self._manifest.get("endpoints")
        return endpoints if isinstance(endpoints, list) else []

    async def create(self, spec: ProvisionSpec) -> str:
        # Nothing to provision — but refuse a spec that could never connect,
        # so the misconfiguration fails at launch, not at grading.
        if not self._configured_endpoints:
            raise ProvisionerError(
                "shared-static deployment has no endpoints configured"
            )
        return self._HANDLE

    async def status(self, handle: str) -> str:
        return "running" if self._configured_endpoints else "unknown"

    async def endpoints(self, handle: str) -> list[dict[str, Any]]:
        return list(self._configured_endpoints)

    async def destroy(self, handle: str) -> None:
        return None

    async def list(self) -> list[str]:
        # Shared endpoint: nothing Flagpost-created exists on a backend, so
        # there is never anything for the orphan reaper to collect.
        return []

    async def validate(self) -> list[CheckResult]:
        legs: list[CheckResult] = []
        endpoints = self._configured_endpoints
        if not endpoints:
            legs.append(
                CheckResult(
                    "endpoints_configured",
                    False,
                    'manifest must carry {"endpoints": [...]} with at least '
                    "one entry",
                )
            )
            return legs
        legs.append(
            CheckResult(
                "endpoints_configured",
                True,
                f"{len(endpoints)} endpoint(s) configured",
            )
        )
        for i, ep in enumerate(endpoints):
            kind = ep.get("kind")
            if kind == "tcp" and ep.get("host") and ep.get("port"):
                ok, detail = True, f"tcp {ep['host']}:{ep['port']}"
            elif kind == "http" and ep.get("url"):
                ok, detail = True, f"http {ep['url']}"
            else:
                ok = False
                detail = (
                    "each endpoint needs kind=tcp with host+port, or "
                    f"kind=http with url (entry {i} has: {sorted(ep)})"
                )
            legs.append(CheckResult(f"endpoint_{i}_shape", ok, detail))
        return legs
