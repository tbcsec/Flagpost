"""Competition membership helpers (ARCHITECTURE.md §7.5).

Gaining the competition-scoped **Participant** role is how a competitor gets
``challenge_view`` (and therefore flag submission, scoreboard, hints, tickets).
Two paths grant it — joining/creating a team (team-mode) and joining a
competition directly (the self-serve path, which is the only way in for
individual-mode competitions) — so the grant lives here once rather than being
re-implemented per route.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.role import Role, RoleAssignment


async def effective_permissions(db: AsyncSession, user_id: str) -> dict:
    """The caller's effective permissions, split global vs per-competition (§7.5).

    Lets the frontend gate nav/sections honestly instead of showing everything.
    The client's effective set for a competition is ``global ∪ by_competition[id]``
    — a global Administrator role grants its permissions everywhere.
    """
    rows = (
        await db.execute(
            select(Role.permissions, RoleAssignment.competition_id)
            .join(RoleAssignment, RoleAssignment.role_id == Role.id)
            .where(RoleAssignment.user_id == user_id)
        )
    ).all()
    global_perms: set[str] = set()
    by_competition: dict[str, set[str]] = {}
    for permissions, competition_id in rows:
        if competition_id is None:
            global_perms.update(permissions)
        else:
            by_competition.setdefault(competition_id, set()).update(permissions)
    return {
        "global": sorted(global_perms),
        "by_competition": {k: sorted(v) for k, v in by_competition.items()},
    }


async def ensure_participant_role(
    db: AsyncSession, competition_id: str, user_id: str
) -> bool:
    """Grant the Participant role for ``competition_id`` to ``user_id``.

    Idempotent: a user who already holds it (e.g. re-joining after leaving) is
    not assigned twice. Returns True if a new assignment was added, False if it
    already existed. The caller commits.
    """
    role = await db.scalar(select(Role).where(Role.name == "Participant"))
    if role is None:  # roles unseeded — nothing to grant (shouldn't happen)
        return False
    existing = await db.scalar(
        select(RoleAssignment).where(
            RoleAssignment.user_id == user_id,
            RoleAssignment.competition_id == competition_id,
            RoleAssignment.role_id == role.id,
        )
    )
    if existing is not None:
        return False
    db.add(
        RoleAssignment(
            user_id=user_id, competition_id=competition_id, role_id=role.id
        )
    )
    return True


async def member_competition_ids(db: AsyncSession, user_id: str) -> set[str]:
    """Competition ids ``user_id`` holds any role in (scoped assignments only)."""
    rows = (
        await db.execute(
            select(RoleAssignment.competition_id).where(
                RoleAssignment.user_id == user_id,
                RoleAssignment.competition_id.isnot(None),
            )
        )
    ).all()
    return {competition_id for (competition_id,) in rows}


async def has_global_role(db: AsyncSession, user_id: str) -> bool:
    """Whether ``user_id`` holds any global (competition_id IS NULL) role — i.e.
    an Administrator, who can see every competition (§7.3)."""
    found = await db.scalar(
        select(RoleAssignment.id).where(
            RoleAssignment.user_id == user_id,
            RoleAssignment.competition_id.is_(None),
        )
    )
    return found is not None
