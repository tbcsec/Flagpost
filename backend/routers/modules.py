"""Per-competition optional-module toggle (ARCHITECTURE.md §11.3, §11.1.3).

The admin surface for the loader's runtime state: list the optional modules
with their enabled state for one competition, and flip one. This is **kernel**,
mounted directly in main.py rather than through a module — the loader is kernel
(§11.3), and a module managing modules would invert that layering (same
precedent as auth/realtime).

Rules enforced here:
- required-core modules aren't toggleable (409) — §11.3;
- unknown module ids 404 (only loaded manifests exist to toggle);
- gated on ``edit_competition`` (it's competition configuration);
- every flip emits ``module.enabled`` / ``module.disabled`` (§3.2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.competition import Competition
from models.competition_module import CompetitionModule
from models.user import User
from plugins.loader import all_manifests, loaded_manifest, optional_modules
from schemas.module import ModuleStateOut, ModuleToggle
from utils.event_bus import event_bus

router = APIRouter(
    prefix="/api/competitions/{competition_id}/modules", tags=["modules"]
)


async def _competition_or_404(db: AsyncSession, competition_id: str) -> Competition:
    competition = await db.get(Competition, competition_id)
    if competition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
        )
    return competition


@router.get("/enabled", response_model=list[str])
async def enabled_modules(
    competition_id: str,
    _user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """The enabled **optional** module ids for this competition — a lightweight,
    member-readable read (``challenge_view``, unlike the ``edit_competition``
    management list) so the client can hide the nav entries of disabled modules
    for every viewer, not just admins. Required-core modules are always on, so
    they're not listed here (nothing gates them)."""
    await _competition_or_404(db, competition_id)
    overrides = {
        module_id: enabled
        for module_id, enabled in (
            await db.execute(
                select(CompetitionModule.module_id, CompetitionModule.enabled).where(
                    CompetitionModule.competition_id == competition_id
                )
            )
        ).all()
    }
    return sorted(
        m.id for m in optional_modules() if overrides.get(m.id, True)
    )


@router.get("", response_model=list[ModuleStateOut])
async def list_modules(
    competition_id: str,
    current_user: User = Depends(require_permission("edit_competition")),
    db: AsyncSession = Depends(get_db),
) -> list[ModuleStateOut]:
    """The full module inventory for this competition — required-core modules
    (always on, locked) plus the optional ones with their per-competition
    enabled state. Optional modules first, then core, each id-sorted."""
    await _competition_or_404(db, competition_id)
    overrides = {
        module_id: enabled
        for module_id, enabled in (
            await db.execute(
                select(CompetitionModule.module_id, CompetitionModule.enabled).where(
                    CompetitionModule.competition_id == competition_id
                )
            )
        ).all()
    }
    return [
        ModuleStateOut(
            id=m.id,
            name=m.name,
            version=m.version,
            # Required-core is always on; an optional module has no override row =
            # the §11.3 default of enabled.
            enabled=True if m.required_core else overrides.get(m.id, True),
            required_core=m.required_core,
        )
        for m in sorted(all_manifests(), key=lambda m: (m.required_core, m.id))
    ]


@router.put("/{module_id}", response_model=ModuleStateOut)
async def toggle_module(
    competition_id: str,
    module_id: str,
    body: ModuleToggle,
    current_user: User = Depends(require_permission("edit_competition")),
    db: AsyncSession = Depends(get_db),
) -> ModuleStateOut:
    await _competition_or_404(db, competition_id)
    manifest = loaded_manifest(module_id)
    if manifest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown module"
        )
    if manifest.required_core:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Required-core modules can't be disabled",
        )

    row = await db.scalar(
        select(CompetitionModule).where(
            CompetitionModule.competition_id == competition_id,
            CompetitionModule.module_id == module_id,
        )
    )
    if row is None:
        row = CompetitionModule(
            competition_id=competition_id, module_id=module_id, enabled=body.enabled
        )
        db.add(row)
    else:
        row.enabled = body.enabled
    await db.commit()

    await event_bus.emit(
        "module.enabled" if body.enabled else "module.disabled",
        {
            "competition_id": competition_id,
            "module_id": module_id,
            "user_id": current_user.id,
        },
    )
    return ModuleStateOut(
        id=manifest.id,
        name=manifest.name,
        version=manifest.version,
        enabled=body.enabled,
        required_core=False,  # required-core was rejected above with 409
    )
