"""Authentication routes (ARCHITECTURE.md §7.7, ADR-0003).

register → login → me → refresh → logout. Access tokens are returned in the
body; the refresh token is set as an httpOnly cookie scoped to ``/api/auth``
so it's only ever sent to these endpoints and never readable by JS.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user
from auth.identity import display_name_taken, email_taken, find_by_identifier
from auth.registration_policy import domain_allowed
from auth.setup import instance_needs_setup
from auth.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    refresh_expiry,
    verify_password,
)
from config import settings
from auth.membership import effective_permissions
from db import ensure_aware_utc, get_db, utcnow
from models.email_verification import EmailVerificationToken
from models.password_reset import PasswordResetToken
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.user import RefreshSession, User
from ratelimit import get_rate_limiter
from ratelimit.base import RateLimiter
from utils import mailer
from schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    PermissionsOut,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
    VerifyEmailRequest,
)
from utils.event_bus import event_bus

logger = logging.getLogger("auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

# A valid hash to verify against when a login's account doesn't exist, so a miss
# and a wrong password cost the same argon2 work — otherwise skipping the hash on
# a miss is a user-enumeration timing oracle. Computed once at import.
_DUMMY_PASSWORD_HASH = hash_password("flagpost-login-timing-equalizer")

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


async def _send_verification_email(db: AsyncSession, user: User) -> None:
    """Mint a fresh 24h verification token and mail the confirmation link,
    replacing any tokens the user already had outstanding."""
    import secrets
    from datetime import timedelta

    for existing in (
        await db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id
            )
        )
    ).scalars().all():
        await db.delete(existing)

    raw = secrets.token_urlsafe(32)
    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=_hash_token(raw),
            expires_at=utcnow() + timedelta(hours=24),
        )
    )
    await db.commit()

    origins = settings.cors_origin_list
    base = origins[0] if origins else ""
    link = f"{base}/verify-email?token={raw}"
    await mailer.send_email(
        [str(user.email)],
        "Verify your email address",
        f"Confirm your email address to finish setting up your Flagpost account.\n\n"
        f"Use this link within the next 24 hours:\n{link}\n\n"
        f"If you didn't create this account, you can ignore this email.",
    )


@router.post(
    "/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    body: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    # Before the first-run wizard completes there's no owner — no self-serve
    # accounts until one exists (ADR-0017).
    if await instance_needs_setup(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This instance hasn't been set up yet.",
        )

    # Site-wide registration policy (Admin → Site settings): when closed, only an
    # administrator can mint accounts (Admin → Users).
    site = await db.get(SiteSettings, SITE_SETTINGS_ID)
    if site is not None and not site.registration_open:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration is closed. Contact an administrator for an account.",
        )

    # Email-domain allowlist (#56): public registration only — admin-created
    # accounts and later email edits are unaffected. Enabling it makes email
    # mandatory. The rejection is deliberately generic in both the
    # missing-email and domain-mismatch cases, so it never discloses which
    # domains (or that a domain policy exists at all) are allowed.
    if site is not None and site.email_domain_allowlist_enabled:
        if not body.email or not domain_allowed(
            body.email, site.allowed_email_domains or []
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Registration is not permitted with that email address.",
            )

    # Email verification (#74): when the gate is on, an email is required —
    # there's nothing to verify without one, and joining a competition would
    # otherwise be permanently blocked with no way to add an address.
    if site is not None and site.email_verification_enabled and not body.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An email address is required to verify your account",
        )

    # Display name is the login identifier — must be unique (case-insensitively).
    if await display_name_taken(db, body.display_name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That display name is already taken",
        )
    if body.email is not None and await email_taken(db, body.email):
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
        # Offload argon2 to a thread so this unauthenticated endpoint can't be
        # used to peg the event loop by flooding registrations.
        password_hash=await asyncio.to_thread(hash_password, body.password),
        display_name=body.display_name,
    )
    db.add(user)
    await db.commit()

    await event_bus.emit(
        "user.registered", {"user_id": user.id, "email": user.email}
    )

    # Email verification (#74): mint + mail a confirmation link. The account
    # exists immediately (login works), but stays unverified — the competition
    # join gate is where the unverified state actually bites.
    if site is not None and site.email_verification_enabled and user.email:
        await _send_verification_email(db, user)

    access_token = await _issue_session(db, user, response)
    return TokenResponse(access_token=access_token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    # The identifier is the display name (username) or the email, matched
    # case-insensitively (§7.7).
    user = await find_by_identifier(db, body.identifier)
    # Always run the (expensive) verify — against a dummy hash when the account
    # is missing — so a miss and a wrong password take the same time (no
    # enumeration oracle). Offloaded to a thread so the argon2 work (which
    # blocks for tens of ms) can't stall the event loop under a login flood.
    target_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_ok = await asyncio.to_thread(verify_password, body.password, target_hash)
    if user is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if not user.is_active:
        # Same status as bad credentials would be friendlier for enumeration, but
        # a disabled user needs to know *why* they can't get in.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been disabled. Contact an administrator.",
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

    if user is None or not user.is_active:
        # A banned user's sessions are revoked at ban time; this is the belt to
        # that suspenders in case a session survived.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account has been disabled",
        )

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


@router.get("/me/permissions", response_model=PermissionsOut)
async def my_permissions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PermissionsOut:
    """Effective permissions for the caller, so the frontend can gate nav and
    sections rather than showing everything and relying on backend 403s."""
    perms = await effective_permissions(db, current_user.id)
    return PermissionsOut(global_perms=perms["global"], by_competition=perms["by_competition"])


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
    await event_bus.emit(
        "user.password_changed", {"user_id": current_user.id}
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- self-service password reset (Phase 9, ADR-0003) -------------------------


def _hash_token(raw: str) -> str:
    import hashlib

    return hashlib.sha256(raw.encode()).hexdigest()


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
) -> Response:
    """Email a password-reset link. Always 204 — never reveals whether an
    account exists for the address. No-ops silently if SMTP is unconfigured."""
    import secrets
    from datetime import timedelta

    # Match the email case-insensitively, like login/registration do (§7.7,
    # auth/identity) — otherwise a differently-cased address silently gets no
    # reset email (and the neutral 204 hides that from the user).
    user = await db.scalar(
        select(User).where(func.lower(User.email) == str(body.email).strip().lower())
    )
    if user is not None and user.is_active:
        raw = secrets.token_urlsafe(32)
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=_hash_token(raw),
                expires_at=utcnow() + timedelta(hours=1),
            )
        )
        await db.commit()
        origins = settings.cors_origin_list
        base = origins[0] if origins else ""
        link = f"{base}/reset-password?token={raw}"
        await mailer.send_email(
            [str(body.email)],
            "Reset your password",
            f"Someone requested a password reset for your account.\n\n"
            f"Use this link within the next hour to choose a new password:\n{link}\n\n"
            f"If you didn't request this, you can ignore this email.",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
) -> Response:
    """Set a new password from a valid, unexpired reset token, then revoke every
    refresh session (a reset logs the user out everywhere)."""
    token = await db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == _hash_token(body.token)
        )
    )
    if token is None or ensure_aware_utc(token.expires_at) < utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired",
        )
    user = await db.get(User, token.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Account not found"
        )
    user.password_hash = hash_password(body.new_password)
    # Invalidate the token(s) + every session.
    for t in (
        await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id
            )
        )
    ).scalars().all():
        await db.delete(t)
    for session in (
        await db.execute(
            select(RefreshSession).where(
                RefreshSession.user_id == user.id,
                RefreshSession.revoked_at.is_(None),
            )
        )
    ).scalars().all():
        session.revoked_at = utcnow()
    await db.commit()
    await event_bus.emit("user.password_changed", {"user_id": user.id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- email verification (issue #74) -------------------------------------------


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(
    body: VerifyEmailRequest, db: AsyncSession = Depends(get_db)
) -> Response:
    """Confirm an account's email from a valid, unexpired verification token.
    Generic 400 on either an invalid or expired token — no enumeration."""
    token = await db.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == _hash_token(body.token)
        )
    )
    if token is None or ensure_aware_utc(token.expires_at) < utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This verification link is invalid or has expired",
        )
    user = await db.get(User, token.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Account not found"
        )
    user.email_verified_at = utcnow()
    for t in (
        await db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id
            )
        )
    ).scalars().all():
        await db.delete(t)
    await db.commit()
    await event_bus.emit("user.email_verified", {"user_id": user.id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/resend-verification", status_code=status.HTTP_204_NO_CONTENT)
async def resend_verification(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> Response:
    """Re-send the verification email to the caller's own address. Rate-limited
    to 1/60s per user to guard against mail-bombing an inbox."""
    site = await db.get(SiteSettings, SITE_SETTINGS_ID)
    if site is None or not site.email_verification_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email verification isn't enabled on this instance",
        )
    if not current_user.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add an email address to your account first",
        )
    if current_user.email_verified_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account is already verified",
        )
    allowed = await rate_limiter.hit(
        f"resend-verification:{current_user.id}", limit=1, window_seconds=60
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please wait before requesting another verification email",
        )
    await _send_verification_email(db, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
