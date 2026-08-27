"""Challenge-instance lifecycle service (#266, ADR-0036 §2).

The ``ChallengeInstance`` row *is* the provisioning job: this module walks it
through ``requested → provisioning → running → expiring → destroyed`` (terminal
``failed``) on the background lane, never on the request path. The route creates
a ``requested`` row and emits ``challenge.instance_requested``; the background
listener registered by the module (``plugins/instances``) calls :func:`provision`,
which talks to the provisioner and flips the row to ``running`` or ``failed``.
Teardown (subject destroy, staff kill, TTL expiry) runs through :func:`teardown`.

Port allocation is done at *request* time and recorded on the row's
``endpoints`` (a TCP host:port per declared container port, in declaration
order) so the used-port set a later launch reads is durable. Docker binds those
exact host ports, so the provisioner's read-back agrees. No column is added:
``endpoints`` is the subject-facing connection block and the allocation ledger
at once (it is only *exposed* once the instance is running).

Nothing here raises ``HTTPException`` — eligibility failures raise
:class:`InstanceError` subclasses that the router maps to status codes, so the
service stays reusable by the reaper and tests.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from db import utcnow
from models.challenge_instancing import (
    DEFAULT_MAX_CONCURRENT,
    INSTANCE_ACTIVE_STATUSES,
    INSTANCE_SETTINGS_ID,
    SITE_BACKENDS,
    ChallengeDeployment,
    ChallengeInstance,
    InstanceSettings,
    instance_can_transition,
)
from models.competition import Competition
from utils.event_bus import event_bus
from utils.provisioners import (
    Provisioner,
    ProvisionerError,
    ProvisionSpec,
    SharedStaticProvisioner,
)

logger = logging.getLogger(__name__)

# Final fallback lifetime when neither the deployment nor the competition sets
# one (seconds). One hour: long enough for a session, short enough to reclaim.
DEFAULT_LIFETIME_S = 3600
# How many times a subject may extend one instance (Phase-1 extension policy —
# a simple count cap, no separate column). Beyond this, re-launch.
MAX_EXTENDS = 5


class InstanceError(Exception):
    """A launch/extend precondition the router turns into a 4xx."""


class CapReached(InstanceError):
    """A per-subject / per-competition / global concurrency ceiling is hit."""


class BackendNotReady(InstanceError):
    """The site orchestrating backend is not configured + enabled."""


class PortsExhausted(InstanceError):
    """No free host port remains in the configured range."""


class NotExtendable(InstanceError):
    """The instance can't be extended (not running, or extension cap reached)."""


# --- helpers -----------------------------------------------------------------


def subject_key(instance: ChallengeInstance) -> str:
    """The credited subject — team in team mode, user otherwise (mirrors
    ``Submission`` / the awarded-solve index)."""
    return instance.team_id or instance.user_id


def transition(instance: ChallengeInstance, target: str) -> bool:
    """Advance the row's status if the lifecycle allows it. Returns True when a
    change (or idempotent re-entry) was applied, False when the step is illegal
    — the caller decides whether that's a no-op or a bug."""
    if not instance_can_transition(instance.status, target):
        logger.warning(
            "illegal instance transition %s → %s (instance %s)",
            instance.status,
            target,
            instance.id,
        )
        return False
    instance.status = target
    return True


def lifetime_for(deployment: ChallengeDeployment, competition: Competition) -> int:
    """Effective instance lifetime: the deployment override, else the
    competition's session length, else the platform default."""
    if deployment.lifetime_s:
        return deployment.lifetime_s
    if competition.instance_lifetime_s:
        return competition.instance_lifetime_s
    return DEFAULT_LIFETIME_S


async def load_settings(db):
    """Load the singleton settings with the encrypted registry credential
    **undeferred**, so a later docker-provisioner build (often after the session
    closes) reads a cached plaintext rather than triggering lazy IO on a
    detached instance. Returns None when instancing was never configured."""
    return await db.scalar(
        select(InstanceSettings)
        .options(undefer(InstanceSettings.registry_credentials))
        .where(InstanceSettings.id == INSTANCE_SETTINGS_ID)
    )


def _event_payload(instance: ChallengeInstance) -> dict:
    """Common lifecycle-event payload — carries ids only (activity-room routing
    + audit), never the flag or connection detail."""
    return {
        "competition_id": instance.competition_id,
        "challenge_id": instance.challenge_id,
        "instance_id": instance.id,
        "user_id": instance.user_id,
        "team_id": instance.team_id,
    }


# --- provisioner construction (kind registry) --------------------------------


def _docker_config(settings: InstanceSettings, deployment: ChallengeDeployment):
    """Build a :class:`DockerConfig` from site settings + the deployment's
    egress posture. Imported lazily so the shared-static path (tests, dev) never
    drags in the httpx docker client."""
    from utils.provisioner_docker import DockerConfig

    egress_denied = settings.egress_policy != "allow"
    return DockerConfig(
        endpoint_url=settings.endpoint_url or "",
        public_host=settings.public_host or "",
        egress_denied=egress_denied,
        default_cpu=settings.default_cpu,
        default_memory_mb=settings.default_memory_mb,
        default_pids=settings.default_pids,
        registry_auth=settings.registry_credentials or None,
    )


def provisioner_for(
    settings: InstanceSettings | None,
    deployment: ChallengeDeployment,
    *,
    transport=None,
) -> Provisioner:
    """Instantiate the provisioner kind a *deployment* runs on. ``shared-static``
    is self-contained (its manifest); the orchestrating kinds need site
    settings. ``transport`` is an httpx seam for tests (docker kind only)."""
    kind = deployment.backend
    if kind == "shared-static":
        return SharedStaticProvisioner(deployment.manifest)
    if kind == "docker":
        if settings is None:
            raise ProvisionerError("instances are not configured")
        # Import (which registers the "docker" kind) before any registry lookup.
        from utils.provisioner_docker import DockerProvisioner

        return DockerProvisioner(_docker_config(settings, deployment), transport=transport)
    # A kind the authoring layer accepts (DEPLOYMENT_BACKENDS) but that has no
    # runtime yet — e.g. kubernetes lands in Phase 3.
    raise ProvisionerError(f"the {kind!r} backend is not available yet")


def provisioner_from_settings(settings: InstanceSettings, *, transport=None) -> Provisioner:
    """Site-level provisioner with no deployment overrides — for the orphan
    reaper (``list``/``destroy``) and the admin test-connection. Only the
    orchestrating backends have a site-level provisioner."""
    if settings.backend == "docker":
        from utils.provisioner_docker import DockerConfig, DockerProvisioner

        egress_denied = settings.egress_policy != "allow"
        cfg = DockerConfig(
            endpoint_url=settings.endpoint_url or "",
            public_host=settings.public_host or "",
            egress_denied=egress_denied,
            default_cpu=settings.default_cpu,
            default_memory_mb=settings.default_memory_mb,
            default_pids=settings.default_pids,
            registry_auth=settings.registry_credentials or None,
        )
        return DockerProvisioner(cfg, transport=transport)
    raise ProvisionerError(f"the {settings.backend!r} backend has no site provisioner")


# --- port allocation ---------------------------------------------------------


async def _used_host_ports(db) -> set[int]:
    """Every TCP host port currently claimed by an active instance. Read from
    the ``endpoints`` ledger so the set is durable across the request that
    allocates and the background task that binds."""
    rows = (
        await db.execute(
            select(ChallengeInstance.endpoints).where(
                ChallengeInstance.status.in_(INSTANCE_ACTIVE_STATUSES)
            )
        )
    ).scalars().all()
    used: set[int] = set()
    for endpoints in rows:
        for ep in endpoints or []:
            port = ep.get("port")
            if isinstance(port, int):
                used.add(port)
    return used


async def _allocate_host_ports(
    db, settings: InstanceSettings, count: int
) -> list[int]:
    """Lowest ``count`` free ports in the configured range. Raises
    :class:`PortsExhausted` when the range can't satisfy the request — a clean,
    evented refusal, not a crash (ADR-0036 §4)."""
    if count == 0:
        return []
    used = await _used_host_ports(db)
    lo, hi = settings.tcp_port_min, settings.tcp_port_max
    chosen: list[int] = []
    port = lo
    while len(chosen) < count and port <= hi:
        if port not in used:
            chosen.append(port)
        port += 1
    if len(chosen) < count:
        raise PortsExhausted(
            f"no free instance port in range {lo}–{hi} "
            f"({len(used)} in use) — raise the range or reduce concurrency"
        )
    return chosen


async def _plan_endpoints(
    db,
    settings: InstanceSettings | None,
    deployment: ChallengeDeployment,
) -> list[dict]:
    """Connection-detail ledger written on the row at request time. For a
    docker/TCP deployment this allocates one host port per declared container
    port (in order) against the configured public host; other shapes populate
    endpoints later (shared-static from its manifest at provision time) or not
    at all (exposure=none)."""
    if deployment.backend == "docker" and deployment.exposure == "tcp":
        if settings is None:
            raise BackendNotReady("instances are not configured")
        ports = await _allocate_host_ports(db, settings, len(deployment.ports))
        return [
            {"kind": "tcp", "host": settings.public_host, "port": p} for p in ports
        ]
    return []


# --- launch ------------------------------------------------------------------


async def _count_active(db, *, competition_id, challenge_id=None, subject=None) -> int:
    stmt = select(func.count(ChallengeInstance.id)).where(
        ChallengeInstance.status.in_(INSTANCE_ACTIVE_STATUSES)
    )
    if competition_id is not None:
        stmt = stmt.where(ChallengeInstance.competition_id == competition_id)
    if challenge_id is not None:
        stmt = stmt.where(ChallengeInstance.challenge_id == challenge_id)
    if subject is not None:
        stmt = stmt.where(
            func.coalesce(ChallengeInstance.team_id, ChallengeInstance.user_id)
            == subject
        )
    return int(await db.scalar(stmt) or 0)


async def _lock_admission(db) -> InstanceSettings | None:
    """Serialise launch admission (cap checks + port allocation) against
    concurrent launches by taking a ``FOR UPDATE`` lock on the settings
    singleton — a **global** gate, because the TCP port range and the global
    concurrency ceiling are host-wide, not per-competition. Held to this
    transaction's commit (the ``submissions._lock_subject`` pattern): real on
    Postgres, a no-op the SQLite dialect drops (SQLite serialises writers
    anyway). When instancing was never configured (no row — only reachable for
    shared-static, which allocates no ports), there is nothing host-global to
    protect, so the lock is skipped."""
    settings = await db.get(InstanceSettings, INSTANCE_SETTINGS_ID)
    if settings is not None:
        await db.execute(
            select(InstanceSettings.id)
            .where(InstanceSettings.id == INSTANCE_SETTINGS_ID)
            .with_for_update()
        )
        # Re-read under the lock: the ceilings/port range this launch enforces
        # must be the currently-committed ones, not a value read before the lock.
        # registry_credentials stays deferred (launch never touches it).
        await db.refresh(settings)
    return settings


async def launch(
    db,
    *,
    competition: Competition,
    deployment: ChallengeDeployment,
    user_id: str,
    team_id: str | None,
) -> ChallengeInstance:
    """Create a ``requested`` instance for the subject after checking every
    guardrail, allocate its ports, commit, and emit ``instance_requested``.
    The caller (route) has already checked eligibility that needs its own
    context (module enabled, competition running, permission); this enforces the
    quantitative caps and backend readiness, which the reaper/tests also rely
    on. Returns the row; provisioning happens on the background lane.

    Admission is serialised on the settings singleton (``_lock_admission``) so
    concurrent launches can't both read the same free port / the same
    under-cap count and then both commit — the check-then-insert race the
    per-subject/competition/global caps and the port allocator would otherwise
    have (found in the P1c adversarial review)."""
    settings = await _lock_admission(db)
    # Orchestrating backends must be configured + enabled; shared-static needs
    # no site provisioner (it is fixed endpoints).
    if deployment.backend in SITE_BACKENDS and not (settings and settings.enabled):
        raise BackendNotReady(
            "Challenge instancing isn't configured for this backend yet."
        )

    subject = team_id or user_id

    # Per-subject cap for this challenge (deployment-declared).
    per_subject = await _count_active(
        db,
        competition_id=competition.id,
        challenge_id=deployment.challenge_id,
        subject=subject,
    )
    if per_subject >= deployment.per_subject_cap:
        raise CapReached(
            "You already have the maximum number of running instances for this "
            "challenge."
        )

    # Per-competition ceiling across all challenges (organiser policy).
    if competition.instance_max_alive is not None:
        comp_active = await _count_active(
            db, competition_id=competition.id, subject=subject
        )
        if comp_active >= competition.instance_max_alive:
            raise CapReached(
                "You've reached this competition's limit on simultaneous "
                "instances. Stop one before launching another."
            )

    # Global concurrency backstop (compute exhaustion).
    ceiling = settings.max_concurrent if settings else DEFAULT_MAX_CONCURRENT
    if await _count_active(db, competition_id=None) >= ceiling:
        raise CapReached(
            "The platform is at its instance capacity right now. Try again in a "
            "few minutes."
        )

    endpoints = await _plan_endpoints(db, settings, deployment)
    lifetime = lifetime_for(deployment, competition)

    instance = ChallengeInstance(
        competition_id=competition.id,
        challenge_id=deployment.challenge_id,
        deployment_id=deployment.id,
        user_id=user_id,
        team_id=team_id,
        status="requested",
        endpoints=endpoints,
        expires_at=utcnow() + timedelta(seconds=lifetime),
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    # Commit before emit — the audit consumer opens its own session.
    await event_bus.emit("challenge.instance_requested", _event_payload(instance))
    return instance


# --- provisioning (background lane) ------------------------------------------


def _spec_for(
    instance: ChallengeInstance, deployment: ChallengeDeployment, lifetime: int
) -> ProvisionSpec:
    # Rebuild the container-port → host-port map from the declared ports paired
    # positionally with the allocated endpoints recorded at request time.
    host_ports = {
        cp: ep["port"]
        for cp, ep in zip(deployment.ports, instance.endpoints or [])
        if ep.get("port") is not None
    }
    return ProvisionSpec(
        instance_id=instance.id,
        deployment_id=deployment.id,
        challenge_id=instance.challenge_id,
        competition_id=instance.competition_id,
        image_ref=deployment.image_ref,
        manifest=deployment.manifest,
        exposure=deployment.exposure,
        ports=list(deployment.ports),
        env=dict(deployment.env or {}),
        resource_limits=deployment.resource_limits,
        lifetime_s=lifetime,
        subject_key=subject_key(instance),
        host_ports=host_ports,
        # Shared-flag mode (Phase 1): no per-instance flag injected. Unique
        # flags arrive in Phase 2.
        flag_plaintext=None,
    )


async def provision(db_factory, instance_id: str) -> None:
    """Background job: take a ``requested`` instance to ``running`` (or
    ``failed``). Runs off the request path (ADR-0012). Idempotent — a second
    delivery of ``instance_requested`` finds the row already past ``requested``
    and returns."""
    async with db_factory() as db:
        instance = await db.get(ChallengeInstance, instance_id)
        if instance is None or instance.status != "requested":
            return
        deployment = await db.get(ChallengeDeployment, instance.deployment_id)
        competition = await db.get(Competition, instance.competition_id)
        settings = await load_settings(db)
        if deployment is None or competition is None:
            transition(instance, "failed")
            instance.failure_reason = "deployment or competition went away"
            await db.commit()
            await event_bus.emit(
                "challenge.instance_provision_failed", _event_payload(instance)
            )
            return
        transition(instance, "provisioning")
        await db.commit()

    lifetime = lifetime_for(deployment, competition)
    spec = _spec_for(instance, deployment, lifetime)
    handle: str | None = None
    try:
        provisioner = provisioner_for(settings, deployment)
        handle = await provisioner.create(spec)
        # Prefer the backend's authoritative connection details (shared-static
        # returns its manifest's; docker confirms the bound host ports).
        resolved = await provisioner.endpoints(handle)
    except Exception as exc:  # noqa: BLE001 — any backend failure is a failed provision
        logger.warning("provision of instance %s failed: %s", instance_id, exc)
        if handle is not None:
            await _safe_destroy(settings, deployment, handle)
        async with db_factory() as db:
            row = await db.get(ChallengeInstance, instance_id)
            if row is not None and row.status not in ("destroyed", "failed"):
                transition(row, "failed")
                row.failure_reason = str(exc)[:500]
                await db.commit()
                await event_bus.emit(
                    "challenge.instance_provision_failed", _event_payload(row)
                )
        return

    async with db_factory() as db:
        row = await db.get(ChallengeInstance, instance_id)
        if row is None:
            # Row deleted mid-provision (challenge removed): don't leak a
            # container.
            await _safe_destroy(settings, deployment, handle)
            return
        if row.status != "provisioning":
            # A concurrent teardown already moved it on; hand the container to
            # that path rather than resurrecting the row.
            await _safe_destroy(settings, deployment, handle)
            return
        transition(row, "running")
        row.backend_handle = handle
        row.started_at = utcnow()
        row.last_seen_at = utcnow()
        if resolved:
            row.endpoints = resolved
        await db.commit()
        await event_bus.emit("challenge.instance_started", _event_payload(row))


async def _safe_destroy(settings, deployment, handle: str) -> None:
    """Best-effort teardown of a leaked/abandoned container. Never raises — a
    persistent failure is left to the orphan reaper."""
    try:
        provisioner = provisioner_for(settings, deployment)
        await provisioner.destroy(handle)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cleanup of container %s failed (orphan): %s", handle, exc)


# --- teardown ----------------------------------------------------------------


async def teardown(
    db_factory, instance_id: str, *, event_name: str = "challenge.instance_destroyed"
) -> None:
    """Tear an instance down: ``→ expiring``, destroy the backend resource,
    ``→ destroyed``. Used by subject destroy, staff kill and the TTL reaper
    (which passes ``challenge.instance_expired``). Idempotent: a row already
    terminal is a no-op; a destroy failure leaves the row ``expiring`` for the
    reaper to retry rather than lying that it's gone."""
    async with db_factory() as db:
        instance = await db.get(ChallengeInstance, instance_id)
        if instance is None or instance.status in ("destroyed", "failed"):
            return
        deployment = await db.get(ChallengeDeployment, instance.deployment_id)
        settings = await load_settings(db)
        # Only a row with a (possible) live container passes through ``expiring``;
        # a ``requested`` row never reached the backend, so it goes straight to
        # ``destroyed`` (requested → expiring isn't a legal step).
        if instance.status in ("running", "provisioning"):
            transition(instance, "expiring")
            await db.commit()
        handle = instance.backend_handle

    if handle is not None and deployment is not None:
        try:
            provisioner = provisioner_for(settings, deployment)
            await provisioner.destroy(handle)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "destroy of instance %s (handle %s) failed; leaving expiring for "
                "the reaper: %s",
                instance_id,
                handle,
                exc,
            )
            return

    async with db_factory() as db:
        instance = await db.get(ChallengeInstance, instance_id)
        if instance is None or instance.status == "destroyed":
            return
        transition(instance, "destroyed")
        instance.destroyed_at = utcnow()
        await db.commit()
        await event_bus.emit(event_name, _event_payload(instance))


# --- extend ------------------------------------------------------------------


async def extend(
    db,
    instance: ChallengeInstance,
    competition: Competition,
    deployment: ChallengeDeployment,
) -> ChallengeInstance:
    """Renew a running instance's lifetime by one session length, within the
    per-instance extension cap. Commits and emits ``instance_extended``."""
    if instance.status != "running":
        raise NotExtendable("Only a running instance can be extended.")
    if instance.extend_count >= MAX_EXTENDS:
        raise NotExtendable(
            f"This instance has reached its extension limit ({MAX_EXTENDS})."
        )
    lifetime = lifetime_for(deployment, competition)
    instance.expires_at = utcnow() + timedelta(seconds=lifetime)
    instance.extend_count += 1
    await db.commit()
    await db.refresh(instance)
    await event_bus.emit("challenge.instance_extended", _event_payload(instance))
    return instance
