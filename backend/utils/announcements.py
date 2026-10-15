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
from db import ensure_aware_utc, utcnow
from models.announcement import Announcement
from models.challenge import Challenge
from models.competition import Competition
from models.team import TeamMembership
from models.user import User
from utils.competition_status import has_started


def published_event(announcement: Announcement, **extra) -> dict:
    """The ``announcement.published`` payload — one shape whether an
    announcement is posted by hand, released by the scheduler (#349), posted by
    an automation rule, or sent as a clarification (#450), so the delivery
    module and any automation can't tell them apart. Ids of recipients stay off
    the event (the handler reads the row), and so does anything about who asked
    a clarification: it isn't stored on the announcement at all."""
    return {
        "competition_id": announcement.competition_id,
        "announcement_id": announcement.id,
        "title": announcement.title,
        "body": announcement.body,
        "severity": announcement.severity,
        "audience_type": announcement.audience_type,
        "created_at": announcement.created_at.isoformat(),
        "kind": announcement.kind,
        "challenge_id": announcement.challenge_id,
        "question": announcement.question,
        **extra,
    }


async def hidden_clarification_challenges(
    db: AsyncSession, competition_id: str, rows: list[Announcement]
) -> set[str]:
    """Of the challenges these clarifications are about, the ones a competitor
    can't see right now (a draft, a scheduled release not reached — say it was
    unpublished after the clarification went out — or any challenge before the
    competition starts). Their clarifications are left out of a competitor's
    feed, as the challenge itself is."""
    ids = {a.challenge_id for a in rows if a.kind == "clarification" and a.challenge_id}
    if not ids:
        return set()
    competition = await db.get(Competition, competition_id)
    if competition is None or not has_started(competition):
        return ids
    now = utcnow()
    challenges = (
        await db.scalars(
            select(Challenge).where(
                Challenge.competition_id == competition_id, Challenge.id.in_(ids)
            )
        )
    ).all()
    visible = {
        c.id
        for c in challenges
        if c.state == "published"
        and (c.release_at is None or ensure_aware_utc(c.release_at) <= now)
    }
    return ids - visible


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

    This is the *published* feed: scheduled drafts (``hidden``) are excluded for
    everyone, staff included — they aren't live yet, and staff manage them
    through :func:`list_scheduled_announcements` instead. That keeps the live
    banner/feed identical for a scheduled post whether or not it has fired.
    """
    rows = list(
        (
            await db.execute(
                select(Announcement)
                .where(
                    Announcement.competition_id == competition_id,
                    Announcement.hidden.is_(False),
                )
                .order_by(Announcement.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    if await user_has_permission(db, user.id, "announcement_create", competition_id):
        return rows
    team_ids = await user_team_ids(db, competition_id, user.id)
    hidden = await hidden_clarification_challenges(db, competition_id, rows)
    return [
        a
        for a in rows
        if visible_to_user(a, user_id=user.id, team_ids=team_ids, is_staff=False)
        and a.challenge_id not in hidden
    ]


async def list_scheduled_announcements(
    db: AsyncSession, competition_id: str
) -> list[Announcement]:
    """The pending scheduled announcements (``hidden``) for the staff management
    view (#349), soonest-first by ``publish_at``. Staff-only — the route gates on
    ``announcement_create``; audience isn't filtered because the author sees
    every draft they scheduled, exactly as with the published feed."""
    rows = await db.execute(
        select(Announcement)
        .where(
            Announcement.competition_id == competition_id,
            Announcement.hidden.is_(True),
        )
        .order_by(Announcement.publish_at.asc())
    )
    return list(rows.scalars().all())


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
        targeted = set(announcement.audience_ids or ())
        if not targeted:
            return set()
        # Scope the raw client-supplied list to competition members, so a
        # targeted announcement can't deliver a notification to users outside
        # this competition (#5) — mirrors the "teams"/"all" branches.
        members = await users_with_permission(db, "challenge_view", competition_id)
        return targeted & members
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
