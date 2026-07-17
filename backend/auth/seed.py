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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.permissions import (
    ADMINISTRATOR_PERMISSIONS,
    JUDGE_PERMISSIONS,
    PARTICIPANT_PERMISSIONS,
)
from models.role import Role

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
