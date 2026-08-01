"""Resolving an OIDC login to a local user (ADR-0021, issue #58).

This is the security-critical half of SSO: everything that decides *which local
account* an external identity becomes. Kept out of the router so the rules are
readable in one place and testable without an HTTP round trip.

The order matters and is deliberate:

1. **``(provider_id, sub)``** — an identity we've already linked. The IdP's
   subject is the stable key, so an address changing upstream follows the user
   instead of stranding them or, worse, matching somebody else.
2. **A verified email, on first contact only** — links an external identity to
   an existing local account. Gated on the IdP asserting ``email_verified``,
   because otherwise anyone able to set an arbitrary unverified address at a
   permissive IdP could claim an existing Flagpost account.
3. **JIT-create** — a brand-new account with **no role assignment at all**,
   exactly like public registration (``routers/auth.register``). Per-competition
   Participant comes later, from ``membership.ensure_participant_role`` when the
   user actually joins a competition (§7.5). Granting anything here would be
   granting it *site-wide*, since an assignment with no ``competition_id`` is
   the Administrator mechanism — see ``deps.user_has_permission``.

A JIT-created user gets a random password hash that is never disclosed. That's
what makes "local login is break-glass only" a structural property rather than a
policy: there is no password for such a user to type, so the local form simply
cannot work for them, while genuine local accounts (the ADR-0017 owner) keep
working when the IdP is down.
"""

from __future__ import annotations

import asyncio
import secrets

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.security import hash_password
from db import utcnow
from models.oidc import OidcProvider, UserExternalIdentity
from models.user import User
from utils.event_bus import event_bus


async def unusable_password_hash() -> str:
    """A real argon2 hash of a value nobody holds.

    ``User.password_hash`` is non-nullable, and making it nullable would ripple
    through every password path. Hashing fresh randomness keeps the column
    honest while guaranteeing no password can ever match it.

    Offloaded to a thread for the same reason registration does it: argon2 is
    ~80ms of CPU, and the callback that triggers it is reachable without
    authentication, so running it inline would let a flood of logins stall the
    event loop.
    """
    return await asyncio.to_thread(hash_password, secrets.token_urlsafe(32))


async def _unique_display_name(db: AsyncSession, preferred: str) -> str:
    """Derive a free display name from the IdP's, suffixing on collision.

    Display names are the primary login identifier and case-insensitively
    unique (ADR-0015), so a JIT-provisioned user can't simply take whatever the
    IdP supplied.
    """
    base = (preferred or "user").strip()[:100] or "user"
    candidate = base
    for attempt in range(100):
        exists = await db.scalar(
            select(User.id).where(func.lower(User.display_name) == candidate.lower())
        )
        if exists is None:
            return candidate
        candidate = f"{base}{attempt + 2}"
    # Astronomically unlikely; a random suffix is still better than failing the
    # login outright.
    return f"{base}-{secrets.token_hex(4)}"


def display_name_from_claims(claims: dict, email: str | None) -> str:
    for key in ("preferred_username", "name", "given_name"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if email:
        return email.split("@", 1)[0]
    return "user"






async def _emit_linked(user_id: str, provider: OidcProvider) -> None:
    await event_bus.emit(
        "identity.linked",
        {
            "user_id": user_id,
            "provider_id": provider.id,
            "provider_slug": provider.slug,
        },
    )


async def resolve_identity(
    db: AsyncSession,
    provider: OidcProvider,
    *,
    subject: str,
    email: str | None,
    email_verified: bool,
    claims: dict,
) -> tuple[User, bool]:
    """Return ``(user, created)`` for an authenticated external identity.

    Callers must have validated the ID token before calling this — nothing here
    re-checks the token's authenticity.
    """
    # 1. Already linked.
    identity = await db.scalar(
        select(UserExternalIdentity).where(
            UserExternalIdentity.provider_id == provider.id,
            UserExternalIdentity.subject == subject,
        )
    )
    if identity is not None:
        user = await db.get(User, identity.user_id)
        if user is not None:
            if email and identity.email != email:
                identity.email = email  # display/audit only
                await db.commit()
            return user, False
        # Orphaned link (user deleted but the row survived a cascade gap):
        # drop it and fall through to re-provisioning.
        await db.delete(identity)

    # 2. First contact — attach to an existing local account, but only on an
    #    email the IdP says it verified.
    existing: User | None = None
    if email and email_verified:
        existing = await db.scalar(
            select(User).where(func.lower(User.email) == email.strip().lower())
        )
    if existing is not None:
        db.add(
            UserExternalIdentity(
                user_id=existing.id,
                provider_id=provider.id,
                subject=subject,
                email=email,
            )
        )
        # Commit *before* emitting, like every other write path (see
        # utils/retention.delete_competition_tree): the audit consumer opens its
        # own session, so emitting mid-transaction both blocks on the writer
        # lock and risks recording something that never durably happened.
        await db.commit()
        await _emit_linked(existing.id, provider)
        return existing, False

    # 3. JIT-provision. Deliberately no RoleAssignment: an assignment with no
    #    competition_id grants site-wide (deps.user_has_permission), so granting
    #    the competition-scoped Participant role here would hand every SSO user
    #    permissions on every competition. Local registration grants nothing
    #    either; both paths earn Participant per-competition on join.
    display_name = await _unique_display_name(
        db, display_name_from_claims(claims, email)
    )
    user = User(
        email=email if (email and email_verified) else None,
        password_hash=await unusable_password_hash(),
        display_name=display_name,
        # The IdP already proved control of the address, so re-verifying it
        # through our own mail flow would be theatre. An unverified claim is
        # dropped above, so this only stamps addresses the IdP vouched for.
        email_verified_at=utcnow() if (email and email_verified) else None,
    )
    db.add(user)
    await db.flush()
    db.add(
        UserExternalIdentity(
            user_id=user.id,
            provider_id=provider.id,
            subject=subject,
            email=email,
        )
    )
    await db.commit()  # durable before any handler observes it — see above

    await event_bus.emit("user.registered", {"user_id": user.id, "email": user.email})
    await _emit_linked(user.id, provider)
    return user, True
