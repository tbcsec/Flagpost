"""Announcement audience targeting (#40, ARCHITECTURE.md §4.3).

One module owns "who is this announcement for", because that question is asked
in two places that must never disagree:

- **Read** — :func:`visible_to_user` filters the list endpoint, so a targeted
  announcement is simply absent for anyone outside its audience.
- **Delivery** — :func:`resolve_recipients` expands the audience to user ids for
  the bell notifications and the live push.

**The delivery rule that makes targeting real:** the shared
``announcements/<competition_id>`` WS room fans a frame to *every* connected
member, so a targeted announcement must never be broadcast there — it would
leak the body to the whole competition while merely *looking* targeted. Targeted
announcements are delivered per-recipient over their existing
``/ws/user/<user_id>`` notification room instead (see the announcements module),
which is authorized to exactly that user. "all" keeps the cheap shared
broadcast: no per-user work for the common case.

Staff who can post (``announcement_create``) always see every announcement —
it's their own sent history, not a leak.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import user_has_permission, users_with_permission
from models.announcement import Announcement
from models.team import TeamMembership
from models.user import User


async def user_team_ids(
    db: AsyncSession, competition_id: str, user_id: str
) -> set[str]:
    """The teams this user belongs to in this competition (§6.2 scoped)."""
    rows = await db.execute(
        select(TeamMembership.team_id).where(
            TeamMembership.competition_id == competition_id,
            TeamMembership.user_id == user_id,
        )
    )
    return set(rows.scalars().all())


def visible_to_user(
    announcement: Announcement,
    *,
    user_id: str,
    team_ids: set[str],
    is_staff: bool,
) -> bool:
    """Whether ``user_id`` may see this announcement.

    Pure — the caller supplies the user's team set once, so filtering a list
    costs one membership query rather than one per announcement.
    """
    if is_staff or announcement.audience_type == "all":
        return True
    targets = set(announcement.audience_ids or ())
    if announcement.audience_type == "users":
        return user_id in targets
    if announcement.audience_type == "teams":
        return bool(team_ids & targets)
    # Unknown audience type: fail closed rather than disclose.
    return False


async def list_visible_announcements(
    db: AsyncSession, competition_id: str, user: User
) -> list[Announcement]:
    """Announcements in the competition the caller may see (§4.3, #40), newest
    first. Staff who can post (``announcement_create``) see everything — their own
    sent history; everyone else sees "all" plus what targets them. The team set is
    resolved once, not per row.

    This is the *audience* filter, not the ``challenge_view`` access gate — the
    route applies that with ``require_permission`` (and any non-route caller
    re-applies it).
    """
    rows = list(
        (
            await db.execute(
                select(Announcement)
                .where(Announcement.competition_id == competition_id)
                .order_by(Announcement.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    if await user_has_permission(db, user.id, "announcement_create", competition_id):
        return rows
    team_ids = await user_team_ids(db, competition_id, user.id)
    return [
        a
        for a in rows
        if visible_to_user(a, user_id=user.id, team_ids=team_ids, is_staff=False)
    ]


async def resolve_recipients(
    db: AsyncSession, announcement: Announcement
) -> set[str]:
    """Expand an announcement's audience to the user ids it should reach.

    For "all" that's every competition member — resolved via the ``challenge_view``
    audience query (the same "who can see this competition" gate the read route
    uses), so staff/judges receive competition-wide announcements too.
    """
    competition_id = announcement.competition_id
    if announcement.audience_type == "users":
        return set(announcement.audience_ids or ())
    if announcement.audience_type == "teams":
        target_teams = list(announcement.audience_ids or ())
        if not target_teams:
            return set()
        rows = await db.execute(
            select(TeamMembership.user_id).where(
                TeamMembership.competition_id == competition_id,
                TeamMembership.team_id.in_(target_teams),
            )
        )
        return set(rows.scalars().all())
    return await users_with_permission(db, "challenge_view", competition_id)
