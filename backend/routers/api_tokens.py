"""Personal API tokens (issue #75, §7 — Users & Roles).

Self-service, per-user tokens that authenticate REST requests as their holder
with that holder's own effective permission set (see
``auth/deps.get_current_user``) — an alternative to capturing a browser JWT.

**Minting is self-only.** ``POST /api/api-tokens`` takes no user id: the holder
is always the authenticated caller, so no permission — administrator or
otherwise — can mint a credential that acts as somebody else. That is a
property of the route's shape, not a check that could be forgotten or bypassed.

``manage_api_tokens`` is an *oversight* grant, never an issuance one: it allows
listing every token on the platform and revoking any of them, so a leaked token
can be killed by someone other than its holder. Revocation only removes access,
so the permission cannot be used to gain any.

REST only: not wired into the WebSocket handshake (explicitly out of scope).
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user, require_permission
from auth.security import averify_password, generate_api_token, hash_api_token
from db import get_db, utcnow
from models.api_token import ApiToken
from models.user import User
from ratelimit import get_rate_limiter
from ratelimit.base import RateLimiter
from schemas.api_token import ApiTokenCreate, ApiTokenCreated, ApiTokenOut
from utils.event_bus import event_bus

router = APIRouter(prefix="/api/api-tokens", tags=["api-tokens"])


def _out(token: ApiToken, holder_name: str) -> ApiTokenOut:
    return ApiTokenOut(
        id=token.id,
        user_id=token.user_id,
        user_display_name=holder_name,
        description=token.description,
        created_at=token.created_at,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        revoked_at=token.revoked_at,
    )


async def _revoke(db: AsyncSession, token: ApiToken, *, actor_id: str) -> None:
    """Revoke ``token`` (idempotent) and record who did it.

    Shared by the self-service and oversight routes so the two can't drift. The
    event carries ``actor_user_id`` — the codebase-wide actor convention — so an
    audit reader can tell a holder revoking their own token from an
    administrator revoking it for them.
    """
    if token.revoked_at is not None:
        return
    token.revoked_at = utcnow()
    await db.commit()
    await event_bus.emit(
        "api_token.revoked",
        {
            "api_token_id": token.id,
            "user_id": token.user_id,
            "actor_user_id": actor_id,
        },
    )


# --- Self-service: your own tokens ------------------------------------------


@router.post("", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    body: ApiTokenCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> ApiTokenCreated:
    """Mint a token for **your own** account.

    No permission required: every account may issue credentials for itself, and
    can issue them for nobody else. Requires the current password (step-up
    re-auth, GHSA-vv68): a stolen session alone can't silently mint a long-lived
    credential that would outlive the victim's password change.
    """
    # Throttle before the password check — the mint endpoint takes a password,
    # so unthrottled it would be a brute-force oracle for a stolen session.
    if not await rate_limiter.hit(
        f"api-token-create:{current_user.id}", limit=5, window_seconds=300
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts — please wait a few minutes and try again",
        )
    if not await averify_password(body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
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
        user_id=current_user.id,
        token_hash=hash_api_token(raw),
        description=body.description,
        expires_at=expires_at,
    )
    db.add(token)
    await db.commit()
    # The holder *is* the actor, so `user_id` is correct for the audit log's
    # actor column with no separate actor field needed.
    await event_bus.emit(
        "api_token.created",
        {"api_token_id": token.id, "user_id": current_user.id},
    )
    out = _out(token, current_user.display_name)
    return ApiTokenCreated(**out.model_dump(), token=raw)


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
    return [_out(t, current_user.display_name) for t in tokens]


@router.delete("/me/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_token(
    token_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    token = await db.get(ApiToken, token_id)
    # 404 rather than 403 for a token that isn't yours, so this route never
    # discloses that some other account's token id exists.
    if token is None or token.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API token not found"
        )
    await _revoke(db, token, actor_id=current_user.id)


# --- Oversight: list every token, revoke any — never mint -------------------


@router.get("", response_model=list[ApiTokenOut])
async def list_tokens(
    _user: User = Depends(require_permission("manage_api_tokens")),
    db: AsyncSession = Depends(get_db),
) -> list[ApiTokenOut]:
    # One join rather than a per-row holder lookup: this list spans every
    # account, so an N+1 here would scale with the whole install's token count.
    rows = (
        await db.execute(
            select(ApiToken, User.display_name)
            .join(User, User.id == ApiToken.user_id)
            .order_by(ApiToken.created_at.desc())
        )
    ).all()
    return [_out(token, name) for token, name in rows]


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: str,
    current_user: User = Depends(require_permission("manage_api_tokens")),
    db: AsyncSession = Depends(get_db),
) -> None:
    token = await db.get(ApiToken, token_id)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API token not found"
        )
    await _revoke(db, token, actor_id=current_user.id)
