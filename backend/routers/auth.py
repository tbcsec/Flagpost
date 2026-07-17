"""Authentication routes (ARCHITECTURE.md §7.7, ADR-0003).

register → login → me → refresh → logout. Access tokens are returned in the
body; the refresh token is set as an httpOnly cookie scoped to ``/api/auth``
so it's only ever sent to these endpoints and never readable by JS.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user
from auth.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_expiry,
    verify_password,
)
from config import settings
from db import ensure_aware_utc, get_db, utcnow
from models.role import Role, RoleAssignment
from models.user import RefreshSession, User
from schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from utils.event_bus import event_bus

logger = logging.getLogger("auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/auth"


async def _issue_session(db: AsyncSession, user: User, response: Response) -> str:
    """Create a refresh session, set the httpOnly cookie, return an access token."""
    raw_refresh = generate_refresh_token()
    db.add(
        RefreshSession(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh),
            expires_at=refresh_expiry(),
        )
    )
    await db.commit()

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
    )
    return create_access_token(user.id)


@router.post(
    "/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    body: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # First-ever account bootstraps the platform administrator. This is the
    # only path that grants above Participant; public registration otherwise
    # never does. Guarded by the empty-users check, so it can't be re-triggered.
    is_first_user = (
        await db.scalar(select(func.count()).select_from(User))
    ) == 0

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    db.add(user)
    await db.flush()  # assign user.id before the role assignment / event

    if is_first_user:
        admin_role = await db.scalar(
            select(Role).where(Role.name == "Administrator")
        )
        if admin_role is None:
            # System roles are seeded by the migration; if they're missing the
            # deployment is misconfigured — fail loudly rather than silently
            # creating an admin-less instance.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Administrator role not seeded; run migrations",
            )
        db.add(
            RoleAssignment(
                user_id=user.id, competition_id=None, role_id=admin_role.id
            )
        )
        logger.warning(
            "Bootstrapped first user %s as Administrator (empty users table)",
            body.email,
        )

    await db.commit()
    await event_bus.emit(
        "user.registered", {"user_id": user.id, "email": user.email}
    )

    access_token = await _issue_session(db, user, response)
    return TokenResponse(access_token=access_token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == body.email))
    # Verify even when the user is missing to avoid leaking which emails exist
    # via timing; use a throwaway hash comparison shape.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    access_token = await _issue_session(db, user, response)
    return TokenResponse(access_token=access_token, user=UserOut.model_validate(user))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token",
        )
    session = await db.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_refresh_token(raw)
        )
    )
    if (
        session is None
        or session.revoked_at is not None
        or ensure_aware_utc(session.expires_at) <= utcnow()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Rotate: revoke the presented session and issue a fresh one, so a stolen
    # refresh token is usable at most until the next legitimate refresh.
    session.revoked_at = utcnow()
    user = await db.get(User, session.user_id)
    await db.commit()

    access_token = await _issue_session(db, user, response)
    return TokenResponse(access_token=access_token, user=UserOut.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> Response:
    raw = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw:
        session = await db.scalar(
            select(RefreshSession).where(
                RefreshSession.token_hash == hash_refresh_token(raw)
            )
        )
        if session is not None and session.revoked_at is None:
            session.revoked_at = utcnow()
            await db.commit()
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current_user)
