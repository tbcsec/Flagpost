"""Challenge attachment routes (ROADMAP #10, ARCHITECTURE.md §13.3).

Files are stored under keys namespaced ``<competition_id>/<challenge_id>/…``
and served only via short-lived **signed URLs** — never a public bucket path,
and issuance goes through the same ``challenge_view`` gate as viewing the
challenge itself, so file access can't become a side channel around RBAC.
Uploads/deletes require ``challenge_edit``. Everything is competition-scoped
through the path (§6.2).
"""

from __future__ import annotations

from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from config import settings
from db import get_db
from models.attachment import Attachment
from models.user import User
from routers.challenges import _get_scoped_challenge, load_visible_challenge
from schemas.attachment import AttachmentOut, SignedUrlOut
from storage import get_storage
from storage.base import ObjectStorage
from utils.event_bus import event_bus

router = APIRouter(
    prefix="/api/competitions/{competition_id}/challenges/{challenge_id}/attachments",
    tags=["attachments"],
)

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024  # 50 MB


def _safe_name(filename: str | None) -> str:
    # Strip any directory components a client may have sent; keep just the leaf.
    name = PurePosixPath(filename or "file").name or "file"
    return name.replace("\\", "_")


async def _attachment_or_404(
    db: AsyncSession, challenge_id: str, attachment_id: str
) -> Attachment:
    attachment = await db.scalar(
        select(Attachment).where(
            Attachment.challenge_id == challenge_id,
            Attachment.id == attachment_id,
        )
    )
    if attachment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
        )
    return attachment


@router.get("", response_model=list[AttachmentOut])
async def list_attachments(
    competition_id: str,
    challenge_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
) -> list[Attachment]:
    await load_visible_challenge(db, competition_id, challenge_id, current_user)
    result = await db.execute(
        select(Attachment)
        .where(Attachment.challenge_id == challenge_id)
        .order_by(Attachment.created_at)
    )
    return list(result.scalars().all())


@router.post("", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    competition_id: str,
    challenge_id: str,
    file: UploadFile,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Attachment:
    # Editors may attach to drafts, so the plain scoped lookup (not the
    # draft-hiding one) is correct here.
    await _get_scoped_challenge(db, competition_id, challenge_id)

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file"
        )
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit",
        )

    filename = _safe_name(file.filename)
    object_key = f"{competition_id}/{challenge_id}/{uuid4().hex}_{filename}"
    storage.put(
        object_key, data, file.content_type or "application/octet-stream"
    )

    attachment = Attachment(
        competition_id=competition_id,
        challenge_id=challenge_id,
        filename=filename,
        object_key=object_key,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
    )
    db.add(attachment)
    await db.commit()

    await event_bus.emit(
        "challenge.updated",
        {
            "competition_id": competition_id,
            "challenge_id": challenge_id,
            "user_id": current_user.id,
            "changed_fields": ["attachments"],
        },
    )
    return attachment


@router.get("/{attachment_id}/url", response_model=SignedUrlOut)
async def get_attachment_url(
    competition_id: str,
    challenge_id: str,
    attachment_id: str,
    current_user: User = Depends(require_permission("challenge_view")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> SignedUrlOut:
    # Same visibility gate as viewing the challenge (§13.3) — no file access
    # around a draft/unpublished challenge.
    await load_visible_challenge(db, competition_id, challenge_id, current_user)
    attachment = await _attachment_or_404(db, challenge_id, attachment_id)

    ttl = settings.signed_url_ttl_seconds
    url = storage.presigned_get_url(attachment.object_key, ttl)
    return SignedUrlOut(url=url, expires_in_seconds=ttl)


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    competition_id: str,
    challenge_id: str,
    attachment_id: str,
    current_user: User = Depends(require_permission("challenge_edit")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> None:
    await _get_scoped_challenge(db, competition_id, challenge_id)
    attachment = await _attachment_or_404(db, challenge_id, attachment_id)

    storage.delete(attachment.object_key)
    await db.delete(attachment)
    await db.commit()

    await event_bus.emit(
        "challenge.updated",
        {
            "competition_id": competition_id,
            "challenge_id": challenge_id,
            "user_id": current_user.id,
            "changed_fields": ["attachments"],
        },
    )
