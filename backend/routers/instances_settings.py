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
from sqlalchemy import String, select, type_coerce
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from auth.deps import require_permission
from db import get_db
from models.challenge_instancing import (
    INSTANCE_SETTINGS_ID,
    SITE_BACKENDS,
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


async def _credentials_present(db: AsyncSession) -> bool:
    """Whether a registry credential is stored, read from the raw ciphertext so
    a key mismatch can't 500 the settings page an operator opened to re-enter
    it (the ``ai_admin._api_key_present`` posture)."""
    raw = await db.scalar(
        select(type_coerce(InstanceSettings.__table__.c.registry_credentials, String)).where(
            InstanceSettings.id == INSTANCE_SETTINGS_ID
        )
    )
    return bool(raw)


def _to_out(settings: InstanceSettings, *, credentials_set: bool) -> InstanceSettingsOut:
    out = InstanceSettingsOut.model_validate(settings)
    out.registry_credentials_set = credentials_set
    return out


def _check_enable_invariant(settings: InstanceSettings) -> None:
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
    return _to_out(settings, credentials_set=await _credentials_present(db))


@router.put("/settings", response_model=InstanceSettingsOut)
async def update_settings(
    body: InstanceSettingsUpdate,
    current_user: User = Depends(require_permission("manage_instance_infra")),
    db: AsyncSession = Depends(get_db),
) -> InstanceSettingsOut:
    settings = await _get_or_create(db)

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
    if body.enabled is not None:
        settings.enabled = body.enabled

    _check_enable_invariant(settings)
    await db.commit()
    # Commit before emit — the audit consumer opens its own session.
    await event_bus.emit(
        "instance.settings_updated",
        {"actor_user_id": current_user.id, "enabled": settings.enabled},
    )
    return _to_out(settings, credentials_set=await _credentials_present(db))


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
        .options(undefer(InstanceSettings.registry_credentials))
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
