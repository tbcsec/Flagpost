"""Personal API tokens (issue #75, §7 — Users & Roles).

Administrator-minted, per-user tokens that authenticate REST requests as their
holder with that holder's full effective permission set (see
``auth/deps.get_current_user``) — an alternative to capturing a browser JWT.

Minting/listing-all/revoking-any is ``manage_api_tokens`` (Administrator-only
among the built-ins). A token's own **holder** can also see and revoke their
own tokens from ``/profile`` without that permission (owner call) — the
``/me`` routes below, ownership-checked rather than catalog-gated.

REST only: not wired into the WebSocket handshake (explicitly out of scope).
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user, require_permission
from auth.security import generate_api_token, hash_api_token
from db import get_db, utcnow
from models.api_token import ApiToken
from models.user import User
from schemas.api_token import ApiTokenCreate, ApiTokenCreated, ApiTokenOut
from utils.event_bus import event_bus

router = APIRouter(prefix="/api/api-tokens", tags=["api-tokens"])


async def _out(db: AsyncSession, token: ApiToken) -> ApiTokenOut:
    holder = await db.get(User, token.user_id)
    creator = (
        await db.get(User, token.created_by_user_id)
        if token.created_by_user_id
        else None
    )
    return ApiTokenOut(
        id=token.id,
        user_id=token.user_id,
        user_display_name=holder.display_name if holder else "Unknown user",
        description=token.description,
        created_by_user_id=token.created_by_user_id,
        created_by_display_name=creator.display_name if creator else None,
        created_at=token.created_at,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        revoked_at=token.revoked_at,
    )


async def _get_token_or_404(db: AsyncSession, token_id: str) -> ApiToken:
    token = await db.get(ApiToken, token_id)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API token not found"
        )
    return token


@router.post("", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    body: ApiTokenCreate,
    current_user: User = Depends(require_permission("manage_api_tokens")),
    db: AsyncSession = Depends(get_db),
) -> ApiTokenCreated:
    holder = await db.get(User, body.user_id)
    if holder is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    try:
        expires_at = utcnow() + timedelta(days=body.expires_in_days)
    except OverflowError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="expires_in_days is too large",
        )

    raw = generate_api_token()
    token = ApiToken(
        user_id=holder.id,
        token_hash=hash_api_token(raw),
        description=body.description,
        created_by_user_id=current_user.id,
        expires_at=expires_at,
    )
    db.add(token)
    await db.commit()
    await event_bus.emit(
        "api_token.created",
        {
            "api_token_id": token.id,
            "user_id": token.user_id,
            "created_by_user_id": current_user.id,
        },
    )
    out = await _out(db, token)
    return ApiTokenCreated(**out.model_dump(), token=raw)


@router.get("", response_model=list[ApiTokenOut])
async def list_tokens(
    _user: User = Depends(require_permission("manage_api_tokens")),
    db: AsyncSession = Depends(get_db),
) -> list[ApiTokenOut]:
    tokens = (
        await db.scalars(select(ApiToken).order_by(ApiToken.created_at.desc()))
    ).all()
    return [await _out(db, t) for t in tokens]


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: str,
    _user: User = Depends(require_permission("manage_api_tokens")),
    db: AsyncSession = Depends(get_db),
) -> None:
    token = await _get_token_or_404(db, token_id)
    if token.revoked_at is None:
        token.revoked_at = utcnow()
        await db.commit()
        await event_bus.emit(
            "api_token.revoked",
            {"api_token_id": token.id, "user_id": token.user_id},
        )


# --- Self-service (own tokens only, no manage_api_tokens needed) -----------


@router.get("/me", response_model=list[ApiTokenOut])
async def list_my_tokens(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ApiTokenOut]:
    tokens = (
        await db.scalars(
            select(ApiToken)
            .where(ApiToken.user_id == current_user.id)
            .order_by(ApiToken.created_at.desc())
        )
    ).all()
    return [await _out(db, t) for t in tokens]


@router.delete("/me/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_token(
    token_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    token = await _get_token_or_404(db, token_id)
    if token.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API token not found"
        )
    if token.revoked_at is None:
        token.revoked_at = utcnow()
        await db.commit()
        await event_bus.emit(
            "api_token.revoked",
            {"api_token_id": token.id, "user_id": token.user_id},
        )
