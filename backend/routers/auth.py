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
from auth.external_identity import IdentityRejected, resolve_identity
from auth.identity import display_name_taken, email_taken, find_by_identifier
from auth.registration_policy import domain_allowed
from auth.setup import instance_needs_setup
from auth.security import (
    ahash_password,
    averify_password,
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
from models.identity_provider import IdentityProvider
from models.password_reset import PasswordResetToken
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.user import RefreshSession, User
from ratelimit import get_rate_limiter
from ratelimit.base import RateLimiter
from schemas.auth_providers import provider_config_or_none
from utils import ldap as ldap_utils
from utils import mailer
from schemas.auth import (
    ChangeEmailRequest,
    ChangePasswordRequest,
    ChangeUsernameRequest,
    ForgotPasswordRequest,
    LoginRequest,
    PermissionsOut,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
    VerifyEmailRequest,
)
from utils.api_tokens import emit_revoked, revoke_user_api_tokens
from utils.event_bus import event_bus

logger = logging.getLogger("auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

# A valid hash to verify against when a login's account doesn't exist, so a miss
# and a wrong password cost the same argon2 work — otherwise skipping the hash on
# a miss is a user-enumeration timing oracle. Computed once at import.
_DUMMY_PASSWORD_HASH = hash_password("flagpost-login-timing-equalizer")

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/auth"


async def _throttle(
    rate_limiter: RateLimiter,
    key: str,
    *,
    limit: int | None = None,
    window: int | None = None,
) -> None:
    """Reject the request if ``key`` has exceeded its window, else record a hit.

    Applied to the unauthenticated credential endpoints, which previously had no
    throttle and no lockout of any kind — a breach corpus could be replayed
    against /login at full concurrency, and forgot-password would mail any
    address as often as asked.

    The key is always lowercased so ``Ada`` and ``ada`` share a bucket; the
    identifier lookup is case-insensitive (§7.7), so keying case-sensitively
    would hand out a fresh budget per capitalisation.
    """
    allowed = await rate_limiter.hit(
        key.lower(),
        limit=limit if limit is not None else settings.auth_rate_limit,
        window_seconds=(
            window if window is not None else settings.auth_rate_window_seconds
        ),
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts — please wait a few minutes and try again",
        )


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
    body: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> TokenResponse:
    # Unauthenticated, and each call costs an argon2 hash plus a row. Keyed on
    # the requested display name so a flood has to vary it, which is also what
    # makes the accounts distinguishable afterwards.
    await _throttle(rate_limiter, f"register:{body.display_name}")
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
        # Offload argon2 to the bounded hashing pool (#207) so this
        # unauthenticated endpoint can't peg the event loop or oversubscribe
        # cores across workers under a registration flood.
        password_hash=await ahash_password(body.password),
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


async def _directory_login(
    db: AsyncSession, identifier: str, password: str
) -> User | None:
    """Offer the submitted credentials to each enabled LDAP directory
    (ADR-0022 §5), returning the resolved local user on the first success.

    Runs only after local verification failed — the ADR-0017 owner and any
    real-password account never touch a directory, and a returning LDAP user
    (whose local hash is the unusable JIT one) falls through here by design.
    A provider whose stored config no longer validates, or whose directory is
    down, is a logged skip: the caller's generic 401 must not leak which.
    """
    providers = (
        await db.scalars(
            select(IdentityProvider)
            .where(
                IdentityProvider.kind == "ldap",
                IdentityProvider.enabled.is_(True),
            )
            .order_by(IdentityProvider.created_at)
        )
    ).all()
    for provider in providers:
        config = provider_config_or_none(provider)
        if config is None:
            logger.warning(
                "LDAP provider %s has invalid stored config; skipping it",
                provider.slug,
            )
            continue
        try:
            # Off the event loop: the bind is blocking network I/O with a
            # TIMEOUT_SECONDS ceiling, like the argon2 work above it. Called
            # through the module so tests can substitute the directory seam.
            found = await asyncio.to_thread(
                ldap_utils.authenticate,
                config,
                provider.secret,
                identifier,
                password,
            )
        except ldap_utils.LdapUnavailable:
            logger.warning(
                "LDAP provider %s is unavailable; treating as a failed attempt",
                provider.slug,
                exc_info=True,
            )
            continue
        if found is None:
            continue
        try:
            user, _created = await resolve_identity(
                db,
                provider,
                subject=found.subject,
                # Honest per ADR-0022 §3: a directory `mail` attribute is not
                # proof of address ownership. Whether the email may link or be
                # stored is decided inside resolve_identity from the provider's
                # `email_is_authoritative` flag, not from this parameter.
                email=found.email,
                email_verified=False,
                claims={"name": found.display_name} if found.display_name else {},
            )
        except IdentityRejected:
            # Unreachable for a closed provider (the admission gate doesn't
            # apply, and the API forces LDAP posture closed) — but a drifted
            # row lands on the gate, and a gated refusal must stay a generic
            # failed login here, not a 500.
            logger.warning(
                "LDAP provider %s rejected by admission policy — posture drift?",
                provider.slug,
            )
            continue
        return user
    return None


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> TokenResponse:
    # Throttle before the lookup, so a refused attempt costs nothing and the
    # limit can't be probed by timing. Keyed per identifier — see the note on
    # `auth_rate_limit` about why not per IP. Deliberately ahead of the LDAP
    # leg below too, so the directory can't be probed unthrottled (ADR-0022 §5).
    await _throttle(rate_limiter, f"login:{body.identifier}")
    # The identifier is the display name (username) or the email, matched
    # case-insensitively (§7.7).
    user = await find_by_identifier(db, body.identifier)
    # Always run the (expensive) verify — against a dummy hash when the account
    # is missing — so a miss and a wrong password take the same time (no
    # enumeration oracle). Offloaded to the bounded hashing pool (#207) so the
    # argon2 work can't stall the event loop or oversubscribe cores across
    # workers under a login storm.
    target_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_ok = await averify_password(body.password, target_hash)
    if user is None or not password_ok:
        # Local failure falls through to the directory before 401ing
        # (ADR-0022 §5). Both failure shapes take this branch, so the accepted
        # residual timing signal (a bind round-trip on the miss path) doesn't
        # distinguish "no such user" from "wrong password".
        user = await _directory_login(db, body.identifier, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if not user.is_active:
        # Same status as bad credentials would be friendlier for enumeration, but
        # a disabled user needs to know *why* they can't get in. Load-bearing for
        # LDAP: the directory bind *succeeds* for a locally-banned user (the
        # directory doesn't know about the ban), so this check is the only thing
        # standing between them and a session (ADR-0022 §5).
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

    Personal API tokens (#75) deliberately **survive** this. Proving the current
    password makes it routine hygiene rather than account recovery, and killing
    a CI credential on every password rotation would be a surprise rather than a
    safeguard (GitHub and GitLab draw the line in the same place). The
    compromise paths do revoke them — a forgotten-password reset, an
    administrator setting the password, a ban — and a holder can revoke any of
    their own tokens from /profile at any time.
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


@router.post("/change-username", response_model=UserOut)
async def change_username(
    body: ChangeUsernameRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> User:
    """Change the caller's own username (display name), the primary login handle.

    Own-user, so no catalog permission — the same posture as change-email. The
    **current password is required** (a stolen session must not be able to seize
    the login identifier), and a **cooldown** (models.user.USERNAME_CHANGE_COOLDOWN,
    stamped in ``username_changed_at``) rate-limits changes over days — spam
    prevention that has to survive restarts, so it lives in the DB, not Redis.
    The per-request Redis limit below is only the brute-force guard on the
    password field.

    Sessions are **not** revoked: identity keys on the immutable user id (the JWT
    ``sub``), so a rename doesn't invalidate anything. The rename emits
    ``user.renamed`` carrying old/new — the audit log is the only place the prior
    name survives, since every other surface renames retroactively.
    """
    # Throttle before the password check — an unthrottled password-taking
    # endpoint is a brute-force oracle for a stolen session (as change-email).
    if not await rate_limiter.hit(
        f"change-username:{current_user.id}", limit=5, window_seconds=300
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts — please wait a few minutes and try again",
        )
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    new_name = body.new_display_name.strip()
    if not new_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Enter a username"
        )
    if new_name == current_user.display_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That's already your username",
        )

    allowed_at = current_user.username_change_allowed_at
    if allowed_at is not None and utcnow() < ensure_aware_utc(allowed_at):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You've changed your username recently — try again later",
        )

    # exclude_id lets a pure case fix ("alice" → "Alice") through, since the
    # case-insensitive index would otherwise flag the name as taken by *self*.
    if await display_name_taken(db, new_name, exclude_id=current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username is already taken",
        )

    old_name = current_user.display_name
    current_user.display_name = new_name
    current_user.username_changed_at = utcnow()
    await db.commit()
    await event_bus.emit(
        "user.renamed",
        {
            "user_id": current_user.id,
            "old_name": old_name,
            "new_name": new_name,
            "actor_user_id": current_user.id,
        },
    )
    return current_user


# --- self-service password reset (Phase 9, ADR-0003) -------------------------


def _hash_token(raw: str) -> str:
    import hashlib

    return hashlib.sha256(raw.encode()).hexdigest()


async def _drop_tokens(db: AsyncSession, model, user_id: str) -> None:
    """Delete every outstanding token of ``model`` for a user."""
    for token in (
        await db.execute(select(model).where(model.user_id == user_id))
    ).scalars().all():
        await db.delete(token)


@router.post("/change-email", response_model=UserOut)
async def change_email(
    body: ChangeEmailRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> UserOut:
    """Add, change or clear the caller's own email address (#106).

    Own-user, so no catalog permission — the same posture as ``change-password``
    and the notification preferences. The **current password is required**: the
    address is where password-reset links go, so a stolen session alone must not
    be enough to repoint it and take the account permanently.

    Refresh sessions are deliberately **not** revoked (unlike a password change).
    The password check already blocks the threat above, and revoking would log
    the legitimate owner out of a routine edit — GitHub and GitLab draw the line
    in the same place. The control that actually helps a victim is the
    notification to the *previous* address, sent below.

    Outstanding password-reset **and** verification tokens are dropped, so a link
    already sitting in the old inbox can't be redeemed after the switch.
    """
    # Limit attempts *before* checking the password: this endpoint takes an
    # arbitrary password guess, so an unthrottled version is a brute-force
    # oracle for anyone holding a stolen session.
    if not await rate_limiter.hit(
        f"change-email:{current_user.id}", limit=5, window_seconds=300
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts — please wait a few minutes and try again",
        )
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    site = await db.get(SiteSettings, SITE_SETTINGS_ID)
    verification_on = bool(site and site.email_verification_enabled)
    previous_email = current_user.email

    if body.new_email is None:
        if verification_on:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This instance requires a verified email, so it can't be removed",
            )
        if previous_email is None:
            return UserOut.model_validate(current_user)  # already clear — no-op
        current_user.email = None
        current_user.email_verified_at = None
    else:
        new_email = str(body.new_email).strip()
        # Resubmitting the same address (any casing) is a no-op: re-running the
        # invalidation would pointlessly kill live reset links, and a fresh
        # verification mail is what /resend-verification is for.
        if previous_email is not None and previous_email.lower() == new_email.lower():
            return UserOut.model_validate(current_user)

        if site and site.email_domain_allowlist_enabled:
            if not domain_allowed(new_email, site.allowed_email_domains or []):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="That email domain isn't allowed on this instance",
                )
        if await email_taken(db, new_email, exclude_id=current_user.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That email is already registered",
            )
        current_user.email = new_email
        # Any change re-opens verification — otherwise verifying a real address
        # and then swapping to another would be a trivial bypass of the gate.
        current_user.email_verified_at = None

    await _drop_tokens(db, PasswordResetToken, current_user.id)
    await _drop_tokens(db, EmailVerificationToken, current_user.id)
    await db.commit()

    # Delivery is best-effort from here. ``send_email`` only no-ops when SMTP is
    # *unconfigured* — a configured-but-unreachable host raises — and the change
    # is already committed, so letting that propagate would return 500 for a
    # change that did happen, and skip the event below. Both mails are
    # recoverable by the user (/resend-verification, or reading the new inbox),
    # so log and carry on.
    if current_user.email and verification_on:
        try:
            await _send_verification_email(db, current_user)
        except Exception:  # noqa: BLE001 — delivery must not fail a done change
            logger.warning(
                "email changed for %s but the verification mail failed",
                current_user.id,
                exc_info=True,
            )

    # Tell the old address, so the real owner learns of a change they didn't
    # make. Skipped on a first-time set — there's nowhere to send it.
    if previous_email:
        try:
            await mailer.send_email(
                [previous_email],
                "Your email address was changed",
                (
                    "The email address on your Flagpost account was just "
                    + (
                        f"changed to {current_user.email}."
                        if current_user.email
                        else "removed."
                    )
                    + "\n\nIf this wasn't you, someone may have access to your "
                    "account — reset your password immediately and contact an "
                    "administrator."
                ),
            )
        except Exception:  # noqa: BLE001 — as above
            logger.warning(
                "could not notify the previous address for %s",
                current_user.id,
                exc_info=True,
            )

    await event_bus.emit(
        "user.updated",
        {"user_id": current_user.id, "actor_user_id": current_user.id},
    )
    return UserOut.model_validate(current_user)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> Response:
    """Email a password-reset link. Always 204 — never reveals whether an
    account exists for the address. No-ops silently if SMTP is unconfigured."""
    # Tighter than the login limit: this endpoint accepts an *arbitrary* address
    # and sends mail to it, so unthrottled it is a mail cannon aimed at anyone
    # and a fast way to burn the instance's SMTP reputation. Contrast
    # /resend-verification, which has always been capped for this exact reason
    # but only covers the caller's own address.
    await _throttle(
        rate_limiter,
        f"forgot-password:{body.email}",
        limit=settings.auth_email_rate_limit,
        window=settings.auth_email_rate_window_seconds,
    )
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
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> Response:
    """Set a new password from a valid, unexpired reset token, then revoke every
    refresh session **and** every personal API token.

    Unlike a voluntary change-password (which proves the current password and
    leaves API tokens alone), reaching this route means the account was
    recovered without knowing the old password — the compromise assumption — so
    every credential the account holds dies with it (#75).
    """
    # Defence in depth. The token is 256 bits of `secrets.token_urlsafe`, so it
    # isn't guessable and this isn't what stands between an attacker and an
    # account — but an unmetered endpoint that takes a bearer-ish secret and
    # tells you whether it's valid should still cost something to hammer.
    await _throttle(rate_limiter, f"reset-password:{body.token[:16]}")
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
    await _drop_tokens(db, PasswordResetToken, user.id)
    for session in (
        await db.execute(
            select(RefreshSession).where(
                RefreshSession.user_id == user.id,
                RefreshSession.revoked_at.is_(None),
            )
        )
    ).scalars().all():
        session.revoked_at = utcnow()
    revoked_tokens = await revoke_user_api_tokens(db, user.id)
    await db.commit()
    await event_bus.emit("user.password_changed", {"user_id": user.id})
    # Self-service recovery: the account holder is the actor.
    await emit_revoked(revoked_tokens, user_id=user.id, actor_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- email verification (issue #74) -------------------------------------------


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(
    body: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> Response:
    """Confirm an account's email from a valid, unexpired verification token.
    Generic 400 on either an invalid or expired token — no enumeration."""
    await _throttle(rate_limiter, f"verify-email:{body.token[:16]}")
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
