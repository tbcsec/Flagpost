"""Marketplace settings (#389, ADR-0040) — the registry + trust config surface.

Admin-only GET/PUT of the ``marketplace_settings`` singleton: the registry a code
resolves against, the trust policy + trusted signing keys, the max installable
tier, and the master on/off switch. The resolve + install pipeline that consumes
this config is the next slice.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import config
from auth.deps import require_permission
from db import get_db
from models.competition import Competition
from models.marketplace import MARKETPLACE_SETTINGS_ID, MarketplaceSettings
from models.user import User
from schemas.content_pack import ContentPackInstallOut
from schemas.marketplace import (
    InstallRequest,
    MarketplaceSettingsOut,
    MarketplaceSettingsUpdate,
    ResolveOut,
    ResolveRequest,
)
from storage import get_storage
from storage.base import ObjectStorage
from utils import marketplace_registry as registry
from utils.content_packs import PackError, apply_pack
from utils.event_bus import event_bus
from utils.marketplace_verify import Signature, TrustedKey, VerificationError, evaluate

# Registry-provided artifact download cap (matches the direct-upload cap in #387).
MAX_ARTIFACT_BYTES = 200 * 1024 * 1024


def get_registry_transport() -> httpx.AsyncBaseTransport | None:
    """Injection seam for the registry HTTP client — tests override this with an
    ``httpx.MockTransport``; production uses the default (a real network client)."""
    return None

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


async def _get_or_create(db: AsyncSession) -> MarketplaceSettings:
    settings = await db.get(MarketplaceSettings, MARKETPLACE_SETTINGS_ID)
    if settings is None:
        settings = MarketplaceSettings(id=MARKETPLACE_SETTINGS_ID)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


def _out(settings: MarketplaceSettings) -> MarketplaceSettingsOut:
    return MarketplaceSettingsOut(
        enabled=settings.enabled,
        registry_url=settings.registry_url,
        trust_policy=settings.trust_policy,
        max_trust_tier=settings.max_trust_tier,
        trusted_keys=settings.trusted_keys or [],
    )


@router.get("/settings", response_model=MarketplaceSettingsOut)
async def get_marketplace_settings(
    _: User = Depends(require_permission("manage_marketplace")),
    db: AsyncSession = Depends(get_db),
) -> MarketplaceSettingsOut:
    return _out(await _get_or_create(db))


@router.put("/settings", response_model=MarketplaceSettingsOut)
async def update_marketplace_settings(
    body: MarketplaceSettingsUpdate,
    current_user: User = Depends(require_permission("manage_marketplace")),
    db: AsyncSession = Depends(get_db),
) -> MarketplaceSettingsOut:
    settings = await _get_or_create(db)
    changes = body.model_dump(exclude_unset=True)
    for field in ("enabled", "registry_url", "trust_policy", "max_trust_tier"):
        if field in changes and changes[field] is not None:
            setattr(settings, field, changes[field])
    if body.trusted_keys is not None:
        settings.trusted_keys = [key.model_dump() for key in body.trusted_keys]
    await db.commit()  # commit before emit (audit consumer opens its own session)
    await db.refresh(settings)
    await event_bus.emit(
        "platform.marketplace_settings_updated", {"actor_user_id": current_user.id}
    )
    return _out(settings)


# --- code resolution + install (#389 Slice B) -------------------------------


async def _require_enabled(db: AsyncSession) -> MarketplaceSettings:
    settings = await _get_or_create(db)
    if not settings.enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The marketplace is disabled"
        )
    return settings


def _verify_artifact(
    data: bytes, resolved: registry.ResolvedArtifact, settings: MarketplaceSettings
) -> None:
    """Local re-verification (docs/MODULES.md §7): the registry's trust claims are
    display hints; the real decision is made here against the instance's policy."""
    signature = None
    if resolved.signature:
        signature = Signature(
            algorithm=str(resolved.signature.get("algorithm", "")),
            key_id=str(resolved.signature.get("key_id", "")),
            value=str(resolved.signature.get("value", "")),
        )
    trusted = [
        TrustedKey(
            key_id=str(k.get("key_id", "")),
            public_key=str(k.get("public_key", "")),
            verified=bool(k.get("verified", False)),
        )
        for k in (settings.trusted_keys or [])
    ]
    evaluate(
        data,
        resolved.digest,
        signature,
        policy=settings.trust_policy,
        root_key=config.MARKETPLACE_ROOT_PUBLIC_KEY or None,
        trusted_keys=trusted,
    )


@router.post("/resolve", response_model=ResolveOut)
async def resolve_code(
    body: ResolveRequest,
    _: User = Depends(require_permission("install_content_pack")),
    db: AsyncSession = Depends(get_db),
    transport: httpx.AsyncBaseTransport | None = Depends(get_registry_transport),
) -> ResolveOut:
    """Resolve a code to the confirmation payload the operator consents to. No
    install, no local verification — that happens at install, after fetch."""
    settings = await _require_enabled(db)
    try:
        resolved = await registry.resolve(
            settings.registry_url, body.code, transport=transport
        )
    except registry.RegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return ResolveOut(
        id=resolved.id,
        name=resolved.name,
        version=resolved.version,
        kind=resolved.kind,
        pack_type=resolved.pack_type,
        trust_tier=resolved.trust_tier,
        publisher=resolved.publisher,
        requires_flagpost=resolved.requires_flagpost,
        capabilities=resolved.capabilities,
        signature_present=resolved.signature is not None,
        installable=resolved.kind == "pack",
    )


@router.post("/install", response_model=ContentPackInstallOut)
async def install_from_marketplace(
    body: InstallRequest,
    current_user: User = Depends(require_permission("install_content_pack")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    transport: httpx.AsyncBaseTransport | None = Depends(get_registry_transport),
) -> ContentPackInstallOut:
    """Resolve → fetch → verify (signature + digest + policy) → apply → audit. A
    bad signature / digest / incompatible pack is refused with a clear reason."""
    settings = await _require_enabled(db)
    competition: Competition | None = None
    if body.competition_id:
        competition = await db.get(Competition, body.competition_id)
        if competition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
            )
    try:
        resolved = await registry.resolve(
            settings.registry_url, body.code, transport=transport
        )
        data = await registry.fetch_artifact(
            resolved.artifact_url, max_bytes=MAX_ARTIFACT_BYTES, transport=transport
        )
    except registry.RegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    try:
        _verify_artifact(data, resolved, settings)
    except VerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"artifact verification failed: {exc}",
        ) from exc
    try:
        summary = await apply_pack(
            db, storage, data, competition=competition, actor_user_id=current_user.id
        )
    except PackError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    await event_bus.emit(
        "platform.content_pack_installed",
        {
            "pack_id": summary["id"],
            "pack_type": summary["pack_type"],
            "target": summary["target"],
            "source": "marketplace",
            "actor_user_id": current_user.id,
        },
    )
    return ContentPackInstallOut(**summary)
