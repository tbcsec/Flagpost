"""Content-pack install (Tier 0 marketplace, #387, ADR-0040).

A single admin-gated endpoint that takes an uploaded content pack, validates it,
and applies it through the existing importers (``utils/content_packs.py``). The
signed registry / code-based import + a confirmation screen are #389; this is the
minimal install path that exercises the pack format end-to-end.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.competition import Competition
from models.user import User
from schemas.content_pack import ContentPackInstallOut
from storage import get_storage
from storage.base import ObjectStorage
from utils.content_packs import PackError, apply_pack
from utils.event_bus import event_bus

router = APIRouter(prefix="/api/content-packs", tags=["content-packs"])

# Upper bound on the uploaded pack, matched to the applier's uncompressed cap.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


@router.post("/install", response_model=ContentPackInstallOut)
async def install_content_pack(
    file: UploadFile = File(...),
    competition_id: str | None = Form(default=None),
    current_user: User = Depends(require_permission("install_content_pack")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> ContentPackInstallOut:
    pack_bytes = await file.read()
    if len(pack_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Pack file too large",
        )

    competition: Competition | None = None
    if competition_id:
        competition = await db.get(Competition, competition_id)
        if competition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found"
            )

    try:
        summary = await apply_pack(
            db,
            storage,
            pack_bytes,
            competition=competition,
            actor_user_id=current_user.id,
        )
    except PackError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    # Commit happened inside apply_pack; emit after (the audit consumer opens its
    # own session). One bulk event — no per-row challenge.created flood.
    await event_bus.emit(
        "platform.content_pack_installed",
        {
            "pack_id": summary["id"],
            "pack_type": summary["pack_type"],
            "target": summary["target"],
            "actor_user_id": current_user.id,
        },
    )
    return ContentPackInstallOut(**summary)
