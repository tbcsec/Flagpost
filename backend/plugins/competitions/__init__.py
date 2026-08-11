"""Competitions module — first consumer of the module loader (§11).

The domain implementation (router, schemas, model) stays in the conventional
`routers/`, `schemas/`, `models/` locations per §14; this package is the
module's manifest + `setup` entry point that wires that router into the app.

Also owns the per-competition ``activity/<competition_id>`` WS room (§4.1) —
the generic "something happened here" channel behind issue #18's live updates.
Unlike the scoreboard room (a shared snapshot everyone sees identically), the
stale surfaces (challenge cards, dashboard widgets, rosters, analytics) are all
per-user filtered, so the room fans out tiny event-name pings and each client
refetches its own permission-filtered REST slice — the same ping→refetch idiom
the tickets module established. Owned here because activity *of a competition*
belongs to the tenancy root, not to any one feature module.
"""

from __future__ import annotations

from config import settings
from utils.coalesce import Coalescer

# Events fanned out to the activity room. A curated allowlist, not "*": frames
# carry the event name + ids only — never payload bodies — so a frame can't
# leak anything the member couldn't refetch anyway. Deliberately absent:
# ticket.* (own opener/staff-scoped rooms), announcement.published (own room,
# carries bodies), user.*/role.*/site.* (global-admin domains, not competition
# activity), automation.*/platform.* (§3.2 non-triggerable families).
ACTIVITY_EVENTS: tuple[str, ...] = (
    "challenge.created",
    "challenge.updated",
    "challenge.published",
    "challenge.deleted",
    "challenge.solved",
    "challenge.attempted",
    "challenge.guesses_reset",
    "challenge.rated",
    "challenge.hint_requested",
    "hint.released",
    "category.created",
    "category.deleted",
    "score.adjusted",
    "achievement.awarded",
    "competition.member_joined",
    "competition.updated",
    "team.created",
    "team.member_joined",
    "team.member_left",
    "team.deleted",
    "scoreboard.frozen",
    "scoreboard.unfrozen",
    "module.enabled",
    "module.disabled",
    "survey.opened",
    "survey.submitted",
)


def setup(app, event_bus, db_factory) -> None:
    # Imported lazily so discovery can read the manifest without importing the
    # whole domain, and to keep module wiring out of import time.
    from auth.deps import user_has_permission
    from db import ensure_aware_utc, utcnow
    from models.challenge import Challenge
    from models.competition import Competition
    from realtime import manager, register_room_type
    from utils.scoreboard import freeze_cutoff
    from utils.scoring import challenge_value, solve_counts
    from routers.awards import router as awards_router
    from routers.brackets import router as brackets_router
    from routers.competitions import router
    from routers.participants import router as participants_router
    from routers.rules import router as rules_router

    app.include_router(router)
    # Rules / code-of-conduct read + accept (#57) — join-adjacent, so it lives
    # with the tenancy root rather than any one feature module.
    app.include_router(rules_router)
    # The individual-mode participant roster (the counterpart to teams); lives
    # with the competitions module since it reads competition membership (§7.5).
    app.include_router(participants_router)
    # Manual judge awards (title/description/points) over the same roster.
    app.include_router(awards_router)
    # Bracket/division self-selection (both modes).
    app.include_router(brackets_router)

    async def authorize_activity(db, user, competition_id: str) -> bool:
        # Same gate as the scoreboard room (§7.6): competitor access to the
        # competition, and the competition must exist so a global admin token
        # can't park sockets in rooms for made-up ids.
        if await db.get(Competition, competition_id) is None:
            return False
        return await user_has_permission(
            db, user.id, "challenge_view", competition_id
        )

    # Broadcast-only, no snapshot: REST is the initial load, the room only
    # tells clients *when* to reload.
    register_room_type("activity", authorize=authorize_activity)

    async def _send_activity(key, team_id=None) -> bool:
        competition_id, event_name, challenge_id = key
        # Nobody watching → don't send (and tell the coalescer nothing was
        # delivered, so it doesn't buffer a trailing ping for a later joiner).
        if manager.room_size("activity", competition_id) == 0:
            return False
        frame: dict = {"type": "activity", "event": event_name}
        # The one id worth carrying: lets clients target per-challenge caches.
        if challenge_id:
            frame["challenge_id"] = challenge_id
        # Solve delta (#188): carry the challenge's *new public* solve_count +
        # value so the ~N watching clients patch that card in place instead of
        # each refetching the whole list (the 4:1 refetch storm), plus the
        # solving team_id so a *teammate* — whose shared solved/locked state
        # changed — knows to refetch (only they do). All three are public: the
        # solves list already discloses which team solved what. Gated on:
        # - the challenge being competitor-visible (don't disclose a draft/
        #   unreleased challenge's count to those who 404 on it), and
        # - the board not being *actively* frozen (solve_count is per-viewer
        #   then — clients fall back to refetching their own frozen slice).
        if event_name == "challenge.solved" and challenge_id:
            async with db_factory() as db:
                competition = await db.get(Competition, competition_id)
                challenge = await db.get(Challenge, challenge_id)
                visible = (
                    challenge is not None
                    and challenge.state == "published"
                    and (
                        challenge.release_at is None
                        or ensure_aware_utc(challenge.release_at) <= utcnow()
                    )
                )
                if (
                    competition is not None
                    and visible
                    and freeze_cutoff(competition) is None
                ):
                    count = (await solve_counts(db, competition_id)).get(challenge_id, 0)
                    frame["solve_count"] = count
                    frame["value"] = challenge_value(challenge, count)
                    if team_id:
                        frame["team_id"] = team_id
        await manager.broadcast("activity", competition_id, frame)
        return True

    # Coalesce per (competition, event, challenge) so a burst collapses to one
    # leading + one trailing broadcast instead of one per event — each broadcast
    # is an N-client refetch/patch, so this caps the storm's width under a burst
    # (#175). Keyed by challenge too (#188) so solves on *different* challenges
    # keep their own deltas rather than collapsing to one; a lone, well-spaced
    # event still fires immediately on the leading edge.
    activity = Coalescer(settings.activity_coalesce_window_seconds, _send_activity)

    async def broadcast_activity(event_name: str, payload: dict) -> None:
        competition_id = payload.get("competition_id")
        if not competition_id:
            return
        await activity.hit(
            (competition_id, event_name, payload.get("challenge_id")),
            payload.get("team_id"),
        )

    for _event in ACTIVITY_EVENTS:
        event_bus.subscribe(_event, broadcast_activity, owner="competitions")
