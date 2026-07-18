"""Seed data for the three built-in system roles (ARCHITECTURE.md §7.3).

``SYSTEM_ROLE_SPECS`` is the single source of truth for the built-ins, consumed
by two callers that must agree:

- the auth migration, which bulk-inserts them at ``upgrade`` time (so a fresh
  ``alembic upgrade head`` provisions a usable platform), and
- ``seed_system_roles``, used by the test fixture (which builds the schema from
  metadata rather than running migrations) and available for idempotent
  re-seeding.

Both read the same specs, so the roles are identical however they're created.
The permission sets themselves live in auth/permissions.py — the catalog is
the source of truth, not this file.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.permissions import (
    ADMINISTRATOR_PERMISSIONS,
    JUDGE_PERMISSIONS,
    PARTICIPANT_PERMISSIONS,
)
from auth.security import hash_password, verify_password
from models.role import Role, RoleAssignment
from models.user import User

logger = logging.getLogger("seed")

# Default administrator, seeded at install time (ADR-0010, supersedes ADR-0007).
# Hardcoded by deliberate choice — these are NOT read from the environment. They
# are a well-known default and MUST be changed after first login (a loud startup
# warning fires while the password is still the default).
# example.com is the IANA-reserved documentation domain — a safe placeholder
# that passes email validation and won't collide with a real address.
DEFAULT_ADMIN_EMAIL = "admin@example.com"
DEFAULT_ADMIN_PASSWORD = "changeme"
DEFAULT_ADMIN_DISPLAY_NAME = "Administrator"

SYSTEM_ROLE_SPECS: list[dict] = [
    {
        "name": "Administrator",
        "description": "Every permission. Manages users, roles, and every competition.",
        "scope": "global",
        "permissions": ADMINISTRATOR_PERMISSIONS,
    },
    {
        "name": "Judge",
        "description": "Full operational control within an assigned competition.",
        "scope": "competition",
        "permissions": JUDGE_PERMISSIONS,
    },
    {
        "name": "Participant",
        "description": "Competitor-facing permissions only.",
        "scope": "competition",
        "permissions": PARTICIPANT_PERMISSIONS,
    },
]


async def seed_system_roles(session: AsyncSession) -> None:
    """Insert any missing built-in roles. Idempotent — safe to call repeatedly."""
    for spec in SYSTEM_ROLE_SPECS:
        existing = await session.scalar(
            select(Role).where(Role.name == spec["name"])
        )
        if existing is not None:
            continue
        session.add(Role(is_system=True, **spec))
    await session.commit()


async def seed_admin_user(session: AsyncSession) -> None:
    """Seed the default administrator user (ADR-0010). Idempotent.

    Requires the system roles to exist already (seed_system_roles / the auth
    migration). Creates the admin with a global Administrator RoleAssignment —
    the one path that grants above Participant, now that public registration
    never does (ADR-0007 superseded).
    """
    existing = await session.scalar(
        select(User).where(User.email == DEFAULT_ADMIN_EMAIL)
    )
    if existing is not None:
        return

    admin_role = await session.scalar(
        select(Role).where(Role.name == "Administrator")
    )
    if admin_role is None:
        raise RuntimeError(
            "Administrator role not seeded; run migrations before seeding the admin"
        )

    user = User(
        email=DEFAULT_ADMIN_EMAIL,
        password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
        display_name=DEFAULT_ADMIN_DISPLAY_NAME,
    )
    session.add(user)
    await session.flush()
    session.add(
        RoleAssignment(user_id=user.id, competition_id=None, role_id=admin_role.id)
    )
    await session.commit()
    logger.info("Seeded default administrator %s", DEFAULT_ADMIN_EMAIL)


async def admin_has_default_password(session: AsyncSession) -> bool:
    """True if the seeded admin exists and its password is still the default.

    Drives the loud startup warning; goes quiet once the admin changes it.
    """
    admin = await session.scalar(
        select(User).where(User.email == DEFAULT_ADMIN_EMAIL)
    )
    if admin is None:
        return False
    return verify_password(DEFAULT_ADMIN_PASSWORD, admin.password_hash)
