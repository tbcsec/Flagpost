"""First-run setup detection (ADR-0017, supersedes the seeded admin of ADR-0010).

An install is "unconfigured" until an **active Administrator** exists. Rather than
seed a default admin with well-known credentials on boot, the instance starts
empty and an operator completes the setup wizard once — which creates the admin
and applies the initial branding / site settings. This helper is the single
source of truth for "are we still on first run", used to gate the wizard endpoint
and to block public registration until an owner is in place.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.role import Role, RoleAssignment
from models.user import User

ADMINISTRATOR_ROLE_NAME = "Administrator"


async def instance_needs_setup(db: AsyncSession) -> bool:
    """True until at least one active user holds the global Administrator role."""
    count = await db.scalar(
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
    return not count
