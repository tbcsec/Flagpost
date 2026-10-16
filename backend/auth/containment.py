"""Delegation containment for account management (GHSA-mwhq-j3jg-p339).

``manage_users`` delegates account administration — the directory, edits,
password resets, bans, deletion. It must not be a delegation of everything: a
holder who could reset an Administrator's password, or change their email and
use Forgot password, would sign in as them and hold every permission.

The rule mirrors the role editor's (``routers.roles._assert_may_grant``): you
can't act on an account holding privilege you don't hold yourself. Privilege
here is every permission the account holds site-wide, plus every permission it
holds in a competition *beyond the Participant floor* — so a help-desk delegate
still resets an ordinary player's password, but not a Judge's or an
Administrator's. Administrator holds the full catalog and is unaffected.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.membership import effective_permissions
from auth.permissions import PARTICIPANT_PERMISSIONS
from models.user import User

_PARTICIPANT_FLOOR = frozenset(PARTICIPANT_PERMISSIONS)


async def privileged_permissions(db: AsyncSession, user_id: str) -> set[str]:
    """What taking over ``user_id``'s account would confer: their site-wide
    permissions, plus their competition permissions above the Participant
    floor (what joining any competition grants)."""
    effective = await effective_permissions(db, user_id)
    privileged = set(effective["global"])
    for permissions in effective["by_competition"].values():
        privileged |= set(permissions) - _PARTICIPANT_FLOOR
    return privileged


async def assert_may_manage_account(
    db: AsyncSession, actor: User, target: User
) -> None:
    """Refuse to change, ban, restore or delete an account holding privilege the
    actor doesn't hold site-wide. Acting on yourself is never an escalation
    (those routes carry their own self-guards)."""
    if actor.id == target.id:
        return
    actor_global = set((await effective_permissions(db, actor.id))["global"])
    missing = sorted(await privileged_permissions(db, target.id) - actor_global)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You can't manage an account holding permissions you don't hold "
                "yourself: " + ", ".join(missing)
            ),
        )
