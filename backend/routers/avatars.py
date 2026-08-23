"""User profile pictures (avatars): self-service upload/remove, admin removal.

Self-service routes are self-only by shape (they act on ``current_user``,
like API-token minting); the admin removal is a moderation tool under the
existing ``manage_users`` permission — no new permission. Every mutation
emits through the event bus (§3), which is what lands it in the audit log.

The stored blob is always the server's own re-encode (``utils/avatars``),
never the uploaded bytes — see that module for the threat model. Serving
still sends the defensive headers the logo path uses; with a re-encoded
raster they're belt-and-braces, and belts are cheap.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from auth.deps import get_current_user, require_permission
from db import get_db, utcnow
from models.user import User
from schemas.auth import UserOut
from utils.avatars import (
    AVATAR_CONTENT_TYPE,
    AVATAR_MAX_UPLOAD_BYTES,
    AvatarError,
    process_avatar,
)
from utils.event_bus import event_bus
from utils.uploads import read_upload_capped

router = APIRouter(tags=["avatars"])


@router.post("/api/profile/avatar", response_model=UserOut)
async def upload_my_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Set the caller's profile picture (replacing any existing one)."""
    data = await read_upload_capped(file, AVATAR_MAX_UPLOAD_BYTES)
    try:
        encoded = process_avatar(data)
    except AvatarError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    current_user.avatar_data = encoded
    current_user.avatar_content_type = AVATAR_CONTENT_TYPE
    current_user.avatar_updated_at = utcnow()
    await db.commit()
    # Commit before emitting (audit consumer opens its own session).
    await event_bus.emit(
        "user.avatar_updated",
        {"user_id": current_user.id, "actor_user_id": current_user.id},
    )
    return current_user


@router.delete("/api/profile/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def remove_my_avatar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove the caller's own profile picture."""
    if current_user.avatar_updated_at is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No avatar set"
        )
    _clear_avatar(current_user)
    await db.commit()
    await event_bus.emit(
        "user.avatar_removed",
        {"user_id": current_user.id, "actor_user_id": current_user.id},
    )


@router.delete("/api/users/{user_id}/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user_avatar(
    user_id: str,
    actor: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Admin moderation: remove any user's profile picture. The emitted event
    carries the acting admin, so the audit log distinguishes moderation from a
    user clearing their own picture."""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such user")
    if user.avatar_updated_at is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No avatar set"
        )
    _clear_avatar(user)
    await db.commit()
    await event_bus.emit(
        "user.avatar_removed", {"user_id": user.id, "actor_user_id": actor.id}
    )


@router.get("/api/users/{user_id}/avatar")
async def read_user_avatar(
    user_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Stream a user's avatar. **Public**, like the site logo: ``<img>`` tags
    can't attach a bearer token, the path is an unguessable uuid, and the blob
    is our own non-sensitive re-encode. Clients append
    ``?v=<avatar_updated_at epoch>``, so the response can be cached hard: a
    changed avatar is a changed URL."""
    user = await db.scalar(
        select(User).where(User.id == user_id).options(undefer(User.avatar_data))
    )
    if user is None or user.avatar_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No avatar set"
        )
    return Response(
        content=user.avatar_data,
        media_type=user.avatar_content_type or AVATAR_CONTENT_TYPE,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            # A re-encoded WebP can't carry script; keep the logo path's
            # defence anyway for a directly-opened URL.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        },
    )


def _clear_avatar(user: User) -> None:
    user.avatar_data = None
    user.avatar_content_type = None
    user.avatar_updated_at = None
