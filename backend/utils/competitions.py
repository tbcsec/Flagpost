"""Competition reads shared beyond the competitions router (§6).

The visibility rule — a competition is visible to a caller if it's public, the
caller holds a role in it, or the caller is a global Administrator — lives here
so every reader enforces it identically rather than re-deriving it. Extracted
from ``routers/competitions`` (it was ``_can_see`` there) so consumers that
aren't inside the competitions request path — the rules router, and later the
assistant tools — call one gate instead of importing across routers.

These functions enforce *visibility scoping*, not the top-level catalog
permission; a route still applies its own ``require_permission`` where one is
required, and a caller reusing these outside a request re-applies whatever gate
its context demands.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from auth.membership import has_global_role, member_competition_ids
from models.competition import Competition
from models.user import User


async def can_see_competition(
    db: AsyncSession, competition: Competition, user: User
) -> bool:
    """Whether ``user`` may see ``competition`` (§6): public, a role in it, or a
    global Administrator."""
    if competition.visibility == "public":
        return True
    if await has_global_role(db, user.id):
        return True
    return competition.id in await member_competition_ids(db, user.id)


async def get_visible_competition(
    db: AsyncSession, competition_id: str, user: User
) -> Competition | None:
    """The competition if the caller may see it, else ``None``.

    ``None`` covers both "doesn't exist" and "exists but private to others", so
    the caller can 404 on either without disclosing which — the existence of a
    private competition isn't revealed.
    """
    competition = await db.get(Competition, competition_id)
    if competition is None or not await can_see_competition(db, competition, user):
        return None
    return competition
