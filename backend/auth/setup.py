"""First-run setup detection (ADR-0017, supersedes the seeded admin of ADR-0010).

An install is "unconfigured" until an **active Administrator** exists. Rather than
seed a default admin with well-known credentials on boot, the instance starts
empty and an operator completes the setup wizard once — which creates the admin
and applies the initial branding / site settings. This helper is the single
source of truth for "are we still on first run", used to gate the wizard endpoint
and to block public registration until an owner is in place.

Two separate questions live here, and conflating them was a vulnerability:

- :func:`active_global_admin_count` — "could this action lock the operator out?"
  It backs every last-admin guard. The predicate was copy-pasted to three call
  sites and one copy drifted, counting bare assignment rows so a *banned*
  administrator still satisfied it.
- :func:`setup_is_complete` — "has this install ever been provisioned?" A
  durable, one-way flag. Zero active administrators is a bad state to be in, but
  it must not reopen the public wizard on a live install, because that turns an
  operator lockout into an anonymous takeover of every competition, flag, user
  record and credential on the box.
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db import utcnow
from models.role import Role, RoleAssignment
from models.site_settings import SITE_SETTINGS_ID, SiteSettings
from models.user import User

ADMINISTRATOR_ROLE_NAME = "Administrator"


async def active_global_admin_count(
    db: AsyncSession, *, exclude_user_id: str | None = None
) -> int:
    """How many **active** users hold the **global** Administrator role.

    ``exclude_user_id`` answers "how many would remain if this user lost it",
    which is the shape every last-admin guard actually needs. Excluding by user
    rather than by assignment id is deliberately conservative: a user holding
    two global Administrator rows counts as gone once, so the guard errs toward
    refusing a removal rather than allowing the count to reach zero.
    """
    stmt = (
        select(func.count())
        .select_from(RoleAssignment)
        .join(Role, Role.id == RoleAssignment.role_id)
        .join(User, User.id == RoleAssignment.user_id)
        .where(
            Role.name == ADMINISTRATOR_ROLE_NAME,
            RoleAssignment.competition_id.is_(None),
            User.is_active.is_(True),
        )
    )
    if exclude_user_id is not None:
        stmt = stmt.where(RoleAssignment.user_id != exclude_user_id)
    return await db.scalar(stmt) or 0


async def instance_needs_setup(db: AsyncSession) -> bool:
    """True until at least one active user holds the global Administrator role.

    Gates public registration and suppresses the update check while an install
    is still unowned. It deliberately does **not** gate the wizard's write path
    — see :func:`setup_is_complete`.
    """
    return not await active_global_admin_count(db)


async def setup_is_complete(db: AsyncSession) -> bool:
    """Whether first-run provisioning has ever finished on this install.

    One-way: nothing clears it. This is what makes re-claiming a configured
    instance impossible regardless of what the role tables happen to say.
    """
    settings = await db.get(SiteSettings, SITE_SETTINGS_ID)
    return settings is not None and settings.setup_completed_at is not None


async def mark_setup_complete(db: AsyncSession) -> bool:
    """Record — atomically and idempotently — that provisioning has finished,
    and return whether **this** call was the one that set it.

    The **single writer** of ``setup_completed_at``. Every path that provisions
    an owner (the wizard, ``seed_admin_user``, ``seed_demo_data``) goes through
    here, so "provisioning an owner marks setup complete" is one function rather
    than an invariant each caller re-implements and can drift from — which is how
    GHSA-ccm4 happened, and then recurred in #132 when the demo seed was the one
    path that hadn't stamped. A future path that forgets is caught by the startup
    consistency check in ``main`` (active admin, but setup never marked).

    **Atomic** via a conditional UPDATE, not a read-then-write: two concurrent
    wizard submissions both pass a plain :func:`setup_is_complete` check, but only
    one UPDATE matches the still-NULL row, so only one provisions an owner and the
    loser gets its 409. The seeds run single-threaded at startup and only need the
    flag set, so they ignore the return.

    Ensures the singleton row exists first (autoflushed so the UPDATE sees it), so
    no caller has to remember to create it.
    """
    if await db.get(SiteSettings, SITE_SETTINGS_ID) is None:
        db.add(SiteSettings(id=SITE_SETTINGS_ID))
        await db.flush()
    result = await db.execute(
        update(SiteSettings)
        .where(
            SiteSettings.id == SITE_SETTINGS_ID,
            SiteSettings.setup_completed_at.is_(None),
        )
        .values(setup_completed_at=utcnow())
    )
    return result.rowcount == 1
