"""Resolving an external login to a local user (ADR-0021, ADR-0022).

This is the security-critical half of external identity: everything that
decides *which local account* an external identity becomes — for any provider
kind. Kept out of the transports so the rules are readable in one place and
testable without an HTTP round trip.

The order matters and is deliberate:

1. **``(provider_id, subject)``** — an identity we've already linked. The
   provider's subject is the stable key, so an address changing upstream
   follows the user instead of stranding them or, worse, matching somebody else.
2. **A trusted email, on first contact only** — links an external identity to
   an existing local account. What "trusted" means depends on the provider's
   ``posture`` (ADR-0022 §2/§3): an **open** provider's email counts only when
   the IdP asserts ``email_verified`` (otherwise anyone able to set an
   arbitrary unverified address at a permissive IdP could claim an existing
   account); a **closed** provider's email counts only when the administrator
   set ``email_is_authoritative`` — a directory's ``mail`` attribute is not,
   by itself, proof of address ownership.
3. **JIT-create** — a brand-new account with **no role assignment at all**,
   exactly like public registration (``routers/auth.register``). The #118
   admission gate (registration-open + domain allowlist) applies to **open**
   providers only: a closed provider being enabled *is* the admission decision
   (ADR-0022 §2). Per-competition Participant comes later, from
   ``membership.ensure_participant_role`` when the user actually joins a
   competition (§7.5). Granting anything here would be granting it *site-wide*,
   since an assignment with no ``competition_id`` is the Administrator
   mechanism — see ``deps.user_has_permission``.

A JIT-created user gets a random password hash that is never disclosed. That's
what makes "local login is break-glass only" a structural property rather than a
policy: there is no password for such a user to type, so the local form simply
cannot work for them, while genuine local accounts (the ADR-0017 owner) keep
working when the IdP is down.
"""

from __future__ import annotations

import secrets

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.registration_policy import domain_allowed
from auth.security import ahash_password
from db import utcnow
from models.identity_provider import IdentityProvider, UserExternalIdentity
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.user import User
from utils.event_bus import event_bus


class IdentityRejected(Exception):
    """An external identity was refused admission by site policy (issue #118).

    Carries a short ``code`` for the callback to surface on ``/login?error=``
    without disclosing whether a local account exists for the address.
    """

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


async def unusable_password_hash() -> str:
    """A real argon2 hash of a value nobody holds.

    ``User.password_hash`` is non-nullable, and making it nullable would ripple
    through every password path. Hashing fresh randomness keeps the column
    honest while guaranteeing no password can ever match it.

    Offloaded to the bounded hashing pool (#207) for the same reason
    registration does it: argon2 is tens of ms of CPU, and the callback that
    triggers it is reachable without authentication, so running it inline would
    let a flood stall the event loop or oversubscribe cores across workers.
    """
    return await ahash_password(secrets.token_urlsafe(32))


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






async def _emit_linked(user_id: str, provider: IdentityProvider) -> None:
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
    provider: IdentityProvider,
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

    # Whether this provider's email claim may be *believed* (ADR-0022 §3).
    # Open providers: the IdP's own email_verified assertion. Closed providers:
    # only the admin's explicit email_is_authoritative flag — a directory bind
    # proves control of the credential, not ownership of the mail attribute.
    email_trusted = bool(email) and (
        (provider.posture == "open" and email_verified)
        or (provider.posture == "closed" and provider.email_is_authoritative)
    )

    # 2. First contact — attach to an existing local account, but only on an
    #    email this provider is trusted to assert.
    existing: User | None = None
    if email_trusted:
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

    # Admission policy for a *new* account (issue #118), **open providers only**
    # (ADR-0022 §3). Only JIT reaches here — an already-linked identity (step 1)
    # and a link to a pre-existing account (step 2) both returned above, so this
    # never locks out an existing user; it mirrors POST /register's controls so
    # a public provider (Google, GitHub) can't create accounts the public form
    # couldn't. A *closed* provider skips the gate deliberately: the admin
    # enabling that directory was the admission decision, and its users often
    # have no verified email for a domain filter to inspect — applying the
    # public-signup gate would lock out the population the admin just admitted.
    # Read the policy with explicit defaults rather than skipping the checks when
    # the settings row is absent. A missing row only ever means a never-configured
    # install (the row is created the moment anyone writes site settings), whose
    # defaults are permissive — but applying those defaults *through the checks*
    # keeps the "no row" path from silently diverging from a configured default if
    # one ever changes, instead of a fail-open skip.
    # `!= "closed"` rather than `== "open"`: posture is a plain string column,
    # and a drifted/unknown value must land on the *restrictive* branch (gate
    # applies), matching how email_trusted above already treats anything that
    # isn't exactly "closed" as untrusted. Only the two Literal values are
    # API-reachable; this is drift hardening, not a reachable state.
    if provider.posture != "closed":
        site = await db.get(SiteSettings, SITE_SETTINGS_ID)
        registration_open = site.registration_open if site is not None else True
        allowlist_enabled = (
            site.email_domain_allowlist_enabled if site is not None else False
        )
        allowed_domains = (
            site.allowed_email_domains if site is not None else None
        ) or []
        if not registration_open:
            raise IdentityRejected("registration_closed")
        if allowlist_enabled and not (
            email_trusted and domain_allowed(email, allowed_domains)
        ):
            # Requires a *trusted* address: the domain gate is only as
            # trustworthy as the claim that the user controls that mailbox.
            raise IdentityRejected("domain_not_allowed")

    # 3. JIT-provision. Deliberately no RoleAssignment: an assignment with no
    #    competition_id grants site-wide (deps.user_has_permission), so granting
    #    the competition-scoped Participant role here would hand every SSO user
    #    permissions on every competition. Local registration grants nothing
    #    either; both paths earn Participant per-competition on join.
    display_name = await _unique_display_name(
        db, display_name_from_claims(claims, email)
    )
    user = User(
        email=email if email_trusted else None,
        password_hash=await unusable_password_hash(),
        display_name=display_name,
        # A trusted claim means the provider already proved (or the admin
        # vouched for) control of the address, so re-verifying it through our
        # own mail flow would be theatre. An untrusted claim is dropped above,
        # so this only stamps addresses someone actually vouched for.
        email_verified_at=utcnow() if email_trusted else None,
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
