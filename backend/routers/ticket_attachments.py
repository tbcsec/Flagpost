"""Support-ticket image attachments (issue #80, §4.4, §13.3).

Screenshots on a ticket thread. Attaching is a follow-up multipart call against
the message that was just created, exactly as challenge attachments follow
challenge creation — so ``create_ticket`` / ``reply_to_ticket`` keep their plain
JSON bodies.

Access mirrors the thread itself (``routers.tickets``): ``_load_visible_ticket``
gives opener-or-staff scoping, and an attachment on a staff **internal note**
is additionally hidden from anyone without ``ticket_view_internal_notes`` — the
thread strips those message bodies, so their images have to disappear with them
rather than remain fetchable by id.

Bytes are served **through this API** (``/content``), not via a presigned
storage URL: the production CSP allows ``img-src 'self' … blob:``, so a
cross-origin MinIO URL would be blocked in an ``<img>``. Same-origin streaming
also lets us serve defensively (``nosniff``, sandbox CSP) the way the site-logo
endpoint does.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import require_permission
from db import get_db
from models.ticket import TicketMessage
from models.ticket_attachment import TicketAttachment
from utils.uploads import read_upload_capped
from models.user import User
from routers.tickets import _load_visible_ticket
from schemas.ticket import TicketAttachmentOut
from storage import get_storage
from storage.base import ObjectStorage
from utils.event_bus import event_bus
from utils.image_sniff import exceeds_pixel_budget, sniff_image_type
from utils.tickets import can_see_internal as _can_see_internal, is_staff as _is_staff

router = APIRouter(
    prefix="/api/competitions/{competition_id}/tickets/{ticket_id}",
    tags=["ticket-attachments"],
)

# Screenshots, not file transfer (issue #80). Both limits are owner decisions.
MAX_TICKET_ATTACHMENT_BYTES = 2_621_440  # 2.5 MB
MAX_ATTACHMENTS_PER_TICKET = 5


def _safe_name(filename: str | None) -> str:
    # Strip any directory components a client may have sent; keep just the leaf.
    name = PurePosixPath(filename or "image").name or "image"
    return name.replace("\\", "_")


async def _message_or_404(
    db: AsyncSession, competition_id: str, ticket_id: str, message_id: str
) -> TicketMessage:
    message = await db.scalar(
        select(TicketMessage).where(
            TicketMessage.competition_id == competition_id,
            TicketMessage.ticket_id == ticket_id,
            TicketMessage.id == message_id,
        )
    )
    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        )
    return message


async def _attachment_or_404(
    db: AsyncSession, competition_id: str, ticket_id: str, attachment_id: str
) -> TicketAttachment:
    attachment = await db.scalar(
        select(TicketAttachment).where(
            TicketAttachment.competition_id == competition_id,
            TicketAttachment.ticket_id == ticket_id,
            TicketAttachment.id == attachment_id,
        )
    )
    if attachment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
        )
    return attachment


async def _assert_message_visible(
    db: AsyncSession, competition_id: str, attachment: TicketAttachment, user: User
) -> None:
    """404 if the attachment hangs off an internal note the viewer can't read.

    The thread filters internal *messages* out of a competitor's view; without
    this the images on those messages would still be fetchable by id, which
    would leak exactly what ``ticket_view_internal_notes`` exists to protect.
    """
    message = await _message_or_404(
        db, competition_id, attachment.ticket_id, attachment.message_id
    )
    if not message.is_internal:
        return
    if not await _can_see_internal(db, user, competition_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
        )


@router.post(
    "/messages/{message_id}/attachments",
    response_model=TicketAttachmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_ticket_attachment(
    competition_id: str,
    ticket_id: str,
    message_id: str,
    file: UploadFile,
    current_user: User = Depends(require_permission("ticket_respond")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> TicketAttachment:
    await _load_visible_ticket(db, competition_id, ticket_id, current_user)
    message = await _message_or_404(db, competition_id, ticket_id, message_id)
    # Only the author of a message may attach to it — otherwise a participant
    # could bolt an image onto a judge's reply (or an internal note).
    if message.author_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only attach to your own message",
        )

    # Bounded read (F6): read at most the cap so the peak allocation is the cap,
    # not the request size — this was the one upload route still doing an
    # unbounded file.read() before the length check. read_upload_capped raises
    # 413 the moment it crosses the cap.
    data = await read_upload_capped(file, MAX_TICKET_ATTACHMENT_BYTES)
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file"
        )
    # Derive the type from the bytes; the client's Content-Type is discarded.
    content_type = sniff_image_type(data)
    if content_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PNG, JPEG and WebP images can be attached",
        )
    # The byte cap alone doesn't bound what it costs to *view* this: a flat
    # 20000x20000 PNG is ~1 MB but decodes to ~1.5 GB in the browser, and
    # thumbnails render the moment staff open the thread. Check the declared
    # dimensions before accepting it.
    if exceeds_pixel_budget(data, content_type):
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Image dimensions are too large to display",
        )

    # The cap is per **ticket**, across every message and author, so it has to
    # be counted over the whole thread rather than the message being added to.
    existing = (
        await db.scalar(
            select(func.count(TicketAttachment.id)).where(
                TicketAttachment.competition_id == competition_id,
                TicketAttachment.ticket_id == ticket_id,
            )
        )
    ) or 0
    if existing >= MAX_ATTACHMENTS_PER_TICKET:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This ticket already has {MAX_ATTACHMENTS_PER_TICKET} attachments",
        )

    filename = _safe_name(file.filename)
    object_key = f"{competition_id}/tickets/{ticket_id}/{uuid4().hex}_{filename}"
    storage.put(object_key, data, content_type)

    attachment = TicketAttachment(
        competition_id=competition_id,
        ticket_id=ticket_id,
        message_id=message_id,
        uploader_user_id=current_user.id,
        filename=filename,
        object_key=object_key,
        content_type=content_type,
        size_bytes=len(data),
    )
    db.add(attachment)
    await db.commit()

    await event_bus.emit(
        "ticket.attachment_added",
        {
            "competition_id": competition_id,
            "ticket_id": ticket_id,
            "message_id": message_id,
            "attachment_id": attachment.id,
            "actor_user_id": current_user.id,
            "is_internal": message.is_internal,
        },
    )
    return attachment


@router.get("/attachments/{attachment_id}/content")
async def read_ticket_attachment(
    competition_id: str,
    ticket_id: str,
    attachment_id: str,
    current_user: User = Depends(require_permission("ticket_view")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> Response:
    """Stream the image bytes for the inline preview (opener **and** staff).

    Served defensively like the site logo: ``nosniff`` plus a sandbox CSP, so a
    file that somehow reached storage as something other than the image we
    sniffed still can't do anything when opened directly.
    """
    await _load_visible_ticket(db, competition_id, ticket_id, current_user)
    attachment = await _attachment_or_404(
        db, competition_id, ticket_id, attachment_id
    )
    await _assert_message_visible(db, competition_id, attachment, current_user)

    try:
        data = storage.get(attachment.object_key)
    except Exception:  # noqa: BLE001 — a missing object is a 404, not a 500
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found"
        ) from None

    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={
            # Ticket images are per-user private; keep them out of shared caches.
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Content-Disposition": "inline",
        },
    )


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ticket_attachment(
    competition_id: str,
    ticket_id: str,
    attachment_id: str,
    current_user: User = Depends(require_permission("ticket_respond")),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> None:
    """Remove an attachment — the **uploader** (mistake) or **staff**
    (moderation). Deleting frees a slot against the per-ticket cap."""
    await _load_visible_ticket(db, competition_id, ticket_id, current_user)
    attachment = await _attachment_or_404(
        db, competition_id, ticket_id, attachment_id
    )
    await _assert_message_visible(db, competition_id, attachment, current_user)

    if attachment.uploader_user_id != current_user.id and not await _is_staff(
        db, current_user, competition_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own attachments",
        )

    message_id = attachment.message_id
    try:
        storage.delete(attachment.object_key)
    except Exception:  # noqa: BLE001 — storage cleanup is best-effort (§13.3)
        pass
    await db.delete(attachment)
    await db.commit()

    await event_bus.emit(
        "ticket.attachment_deleted",
        {
            "competition_id": competition_id,
            "ticket_id": ticket_id,
            "message_id": message_id,
            "attachment_id": attachment_id,
            "actor_user_id": current_user.id,
        },
    )
