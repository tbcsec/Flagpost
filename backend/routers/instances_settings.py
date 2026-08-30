"""Challenge instancing — site infrastructure config (#266, ADR-0036 §5).

Admin → Site settings → Instances. Gated on ``manage_instance_infra`` (its own
grant, not ``manage_site_settings``): this surface points the platform at a
container-runtime endpoint and holds a registry credential, so it is a
higher-stakes control than a palette — the auth-providers / AI reasoning.

The module ships **inert**: ``enabled`` is off until an operator sets a backend,
endpoint and public host, and enabling is refused until they are, so "enabled
but unconfigured" is unreachable. ``registry_credentials`` is write-only and
encrypted (ADR-0020); GET reports only whether one is stored. ``endpoint_url``
is a trusted operator setting — a private socket-proxy address — so it is not
run through the webhook SSRF blocklist. "Test connection" runs the provisioner's
staged ``validate()`` and returns each leg for the UI to render individually.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import String, func, select, type_coerce
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from auth.deps import require_permission
from db import get_db
from models.challenge_instancing import (
    INSTANCE_ACTIVE_STATUSES,
    INSTANCE_SETTINGS_ID,
    SITE_BACKENDS,
    ChallengeDeployment,
    ChallengeInstance,
    InstanceSettings,
)
from models.user import User
from schemas.instances import (
    InstanceSettingsOut,
    InstanceSettingsUpdate,
    TestConnectionLeg,
    TestConnectionResult,
)
from utils.event_bus import event_bus
from utils.instance_service import provisioner_from_settings
from utils.provisioners import ProvisionerError

router = APIRouter(prefix="/api/admin/instances", tags=["instances-admin"])


async def _get_or_create(db: AsyncSession) -> InstanceSettings:
    settings = await db.get(InstanceSettings, INSTANCE_SETTINGS_ID)
    if settings is None:
        settings = InstanceSettings(id=INSTANCE_SETTINGS_ID)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


async def _secret_present(db: AsyncSession, column) -> bool:
    """Whether a write-only secret column is stored, read from the raw
    ciphertext so a key mismatch can't 500 the settings page an operator opened
    to re-enter it (the ``ai_admin._api_key_present`` posture)."""
    raw = await db.scalar(
        select(type_coerce(column, String)).where(
            InstanceSettings.id == INSTANCE_SETTINGS_ID
        )
    )
    return bool(raw)


async def _credentials_present(db: AsyncSession) -> bool:
    return await _secret_present(db, InstanceSettings.__table__.c.registry_credentials)


async def _k8s_token_present(db: AsyncSession) -> bool:
    return await _secret_present(db, InstanceSettings.__table__.c.k8s_bearer_token)


async def _count_active_orchestrated(db: AsyncSession) -> int:
    """Active instances whose teardown routes through the site backend — every
    non-shared-static instance (#320). A site-backend change re-homes their
    destroy path (``effective_backend`` + the backend's config), so the PUT
    refuses the change while any exist rather than strand them."""
    return int(
        await db.scalar(
            select(func.count(ChallengeInstance.id))
            .join(
                ChallengeDeployment,
                ChallengeInstance.deployment_id == ChallengeDeployment.id,
            )
            .where(
                ChallengeInstance.status.in_(INSTANCE_ACTIVE_STATUSES),
                ChallengeDeployment.backend != "shared-static",
            )
        )
        or 0
    )


def _to_out(
    settings: InstanceSettings, *, credentials_set: bool, k8s_token_set: bool
) -> InstanceSettingsOut:
    out = InstanceSettingsOut.model_validate(settings)
    out.registry_credentials_set = credentials_set
    out.k8s_bearer_token_set = k8s_token_set
    return out


def _check_enable_invariant(
    settings: InstanceSettings, *, k8s_token_present: bool
) -> None:
    # The site backend must be a real orchestrating kind. Without this,
    # `{"backend": "shared-static", "enabled": true}` would slip past the
    # endpoint/public-host requirement below (shared-static isn't a SITE_BACKEND)
    # and reach the "enabled but unconfigured" state the module forbids.
    if settings.backend not in SITE_BACKENDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Backend must be one of: {', '.join(SITE_BACKENDS)}.",
        )
    if settings.enabled and not (settings.endpoint_url and settings.public_host):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set an endpoint URL and public host before enabling instances.",
        )
    # The kubernetes kind can't authenticate without a ServiceAccount token
    # (#320) — same "enabled but unconfigured is unreachable" posture. Passed
    # in as a bool because the column is deferred: reading the ORM attribute
    # here would lazy-load (and decrypt) it mid-invariant.
    if (
        settings.enabled
        and settings.backend == "kubernetes"
        and not k8s_token_present
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Store a Kubernetes service-account token before enabling instances.",
        )
    if settings.tcp_port_min > settings.tcp_port_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The TCP port range minimum can't exceed the maximum.",
        )


@router.get("/settings", response_model=InstanceSettingsOut)
async def get_settings(
    current_user: User = Depends(require_permission("manage_instance_infra")),
    db: AsyncSession = Depends(get_db),
) -> InstanceSettingsOut:
    settings = await _get_or_create(db)
    return _to_out(
        settings,
        credentials_set=await _credentials_present(db),
        k8s_token_set=await _k8s_token_present(db),
    )


@router.put("/settings", response_model=InstanceSettingsOut)
async def update_settings(
    body: InstanceSettingsUpdate,
    current_user: User = Depends(require_permission("manage_instance_infra")),
    db: AsyncSession = Depends(get_db),
) -> InstanceSettingsOut:
    settings = await _get_or_create(db)
    # Serialise concurrent settings PUTs on the singleton so two interleaved
    # admin writes can't each pass the enable-invariant on a stale snapshot and
    # commit disjoint columns into the forbidden "enabled but unconfigured"
    # state (the ``_lock_admission`` pattern). Real on Postgres; a no-op the
    # SQLite dialect drops (writers serialise anyway).
    await db.execute(
        select(InstanceSettings.id)
        .where(InstanceSettings.id == INSTANCE_SETTINGS_ID)
        .with_for_update()
    )

    # A site-backend change (docker ⇄ kubernetes) re-homes how EVERY
    # orchestrated instance is torn down: teardown and the reaper resolve the
    # provisioner through the current site backend and its config (#320 D7).
    # Flipping while instances are live would strand them — their destroy would
    # route to a backend that can't hold their handle, leaving them stuck in
    # ``expiring`` with their ports and cap slots leaked. Refuse until they drain.
    if body.backend is not None and body.backend != settings.backend:
        live = await _count_active_orchestrated(db)
        if live:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Stop the {live} running instance(s) before changing the "
                    "provisioner backend."
                ),
            )

    if body.backend is not None:
        settings.backend = body.backend
    if body.endpoint_url is not None:
        settings.endpoint_url = body.endpoint_url.strip() or None
    if body.public_host is not None:
        settings.public_host = body.public_host.strip() or None
    if body.registry_credentials is not None:
        # "" clears it; omitting leaves it untouched (write-only secret).
        settings.registry_credentials = body.registry_credentials or None
    if body.tcp_port_min is not None:
        settings.tcp_port_min = body.tcp_port_min
    if body.tcp_port_max is not None:
        settings.tcp_port_max = body.tcp_port_max
    if body.default_cpu is not None:
        settings.default_cpu = body.default_cpu
    if body.default_memory_mb is not None:
        settings.default_memory_mb = body.default_memory_mb
    if body.default_pids is not None:
        settings.default_pids = body.default_pids
    if body.max_concurrent is not None:
        settings.max_concurrent = body.max_concurrent
    if body.egress_policy is not None:
        settings.egress_policy = body.egress_policy
    if body.chal_base_domain is not None:
        # "" clears it; the schema has already normalised a real value.
        settings.chal_base_domain = body.chal_base_domain or None
    if body.spawn_rate_limit is not None:
        settings.spawn_rate_limit = body.spawn_rate_limit
    if body.spawn_rate_window_seconds is not None:
        settings.spawn_rate_window_seconds = body.spawn_rate_window_seconds
    # Kubernetes kind (#320). The token mirrors registry_credentials: "" clears,
    # omitting leaves it untouched; the schema normalised the rest ("" clears
    # the nullable ones).
    if body.k8s_namespace is not None:
        settings.k8s_namespace = body.k8s_namespace
    if body.k8s_bearer_token is not None:
        settings.k8s_bearer_token = body.k8s_bearer_token or None
    if body.k8s_ca_cert is not None:
        settings.k8s_ca_cert = body.k8s_ca_cert or None
    if body.k8s_ingress_class is not None:
        settings.k8s_ingress_class = body.k8s_ingress_class or None
    if body.k8s_image_pull_secret is not None:
        settings.k8s_image_pull_secret = body.k8s_image_pull_secret or None
    if body.k8s_cluster_cidr is not None:
        settings.k8s_cluster_cidr = body.k8s_cluster_cidr or None
    if body.enabled is not None:
        settings.enabled = body.enabled

    # Deferred column: resolve "is a token stored" without touching the ORM
    # attribute — this request may have just written or cleared it.
    if body.k8s_bearer_token is not None:
        k8s_token_present = bool(body.k8s_bearer_token)
    else:
        k8s_token_present = await _k8s_token_present(db)
    _check_enable_invariant(settings, k8s_token_present=k8s_token_present)
    await db.commit()
    # Commit before emit — the audit consumer opens its own session.
    await event_bus.emit(
        "instance.settings_updated",
        {"actor_user_id": current_user.id, "enabled": settings.enabled},
    )
    return _to_out(
        settings,
        credentials_set=await _credentials_present(db),
        k8s_token_set=k8s_token_present,
    )


async def _run_validation(settings: InstanceSettings) -> list:
    """Build the site provisioner and run its staged ``validate()``. Factored
    out as the seam tests monkeypatch (the real legs are exercised against a
    mock transport in ``test_provisioner_docker``)."""
    provisioner = provisioner_from_settings(settings)
    return await provisioner.validate()


@router.post("/test-connection", response_model=TestConnectionResult)
async def test_connection(
    current_user: User = Depends(require_permission("manage_instance_infra")),
    db: AsyncSession = Depends(get_db),
) -> TestConnectionResult:
    """Probe the *saved* provisioner config leg by leg, so a field
    misconfiguration (unreachable endpoint, unrestricted proxy, non-internal
    network, closed firewall) surfaces before event day, not during it."""
    settings = await db.scalar(
        select(InstanceSettings)
        .options(
            undefer(InstanceSettings.registry_credentials),
            undefer(InstanceSettings.k8s_bearer_token),
        )
        .where(InstanceSettings.id == INSTANCE_SETTINGS_ID)
    )
    if (
        settings is None
        or settings.backend not in SITE_BACKENDS
        or not settings.endpoint_url
        or not settings.public_host
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Set a backend, endpoint URL and public host before testing.",
        )
    try:
        legs = await _run_validation(settings)
    except ProvisionerError as exc:
        legs = [
            _leg_from_error(str(exc)),
        ]
    out_legs = [
        TestConnectionLeg(name=leg.name, ok=leg.ok, detail=leg.detail) for leg in legs
    ]
    return TestConnectionResult(ok=all(leg.ok for leg in out_legs), legs=out_legs)


def _leg_from_error(detail: str):
    from utils.provisioners import CheckResult

    return CheckResult("endpoint_reachable", False, detail)
