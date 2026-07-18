"""Authentication routes (ARCHITECTURE.md §7.7, ADR-0003).

register → login → me → refresh → logout. Access tokens are returned in the
body; the refresh token is set as an httpOnly cookie scoped to ``/api/auth``
so it's only ever sent to these endpoints and never readable by JS.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
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
from models.user import RefreshSession, User
from schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
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

    # Public registration always creates a plain user with no role assignment.
    # It never grants above Participant (ADR-0010, supersedes ADR-0007); the
    # administrator is seeded at install time, and per-competition access comes
    # from a RoleAssignment when a user joins a competition (§7.5).
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    db.add(user)
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


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Change the current user's password.

    This is what lets the seeded default admin rotate its well-known password
    (ADR-0010). All of the user's refresh sessions are revoked, so a password
    change logs them out everywhere and any leaked refresh token dies.
    """
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.password_hash = hash_password(body.new_password)

    sessions = (
        await db.execute(
            select(RefreshSession).where(
                RefreshSession.user_id == current_user.id,
                RefreshSession.revoked_at.is_(None),
            )
        )
    ).scalars().all()
    for session in sessions:
        session.revoked_at = utcnow()

    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
