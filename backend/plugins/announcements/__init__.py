"""Announcements module (ROADMAP #14, §11.3 required-core).

Mounts the announcements router and owns the "announcements" WebSocket room: on
join a client is authorized exactly like the REST read (``challenge_view`` on
the competition) and handed the recent-announcements snapshot. The router stays
transport-agnostic — it emits ``announcement.published``; this module delivers.

Delivery has two lanes (#40), because the shared room fans a frame to *every*
connected member:

- **audience "all"** — the cheap path: broadcast the announcement to the shared
  room, plus one bell notification per member.
- **targeted** — never touches the shared room (that would leak the body to the
  whole competition while merely *looking* targeted). Recipients are resolved
  and reached over their own ``/ws/user/<id>`` rooms, which the notification
  frame already rides; their clients then refetch the server-filtered list.

Either way the join snapshot is audience-filtered too, so a reconnect can't
reveal what the live path withheld. Audience rules live in ``utils/announcements``.
"""

from __future__ import annotations

RECENT_LIMIT = 20

# Recipients per fan-out transaction (#454). The per-recipient work — a prefs
# lookup and one ``Notification`` row each — is linear in audience size, and
# this handler's own history is the evidence: the fan-out for an
# all-participants announcement was measured at ~24s, which is why it moved to
# the background lane in the first place. Committing per batch means a handler
# that is cancelled part-way leaves the batches it finished both committed and
# delivered, instead of rolling back every notification for the announcement.
FANOUT_BATCH = 200

# Declared per-subscription handler bound (#452 added the override; #454 is why
# this handler needs one). The event-bus default is 10s — less than this
# handler's own measured worst case, so delivery was being cancelled before its
# single commit and every notification was lost while the announcement row
# stayed durable: an operator published, saw it listed, and nobody was
# notified. Sized to cover a large competition's fan-out with headroom;
# batching means exceeding it now degrades to a partial delivery rather than a
# total loss.
DELIVER_HANDLER_TIMEOUT = 300.0

# The bell notice for a withdrawn clarification (the title is the challenge's).
WITHDRAWN_NOTICE = "The judges withdrew this clarification — don't rely on it."


def setup(app, event_bus, db_factory) -> None:
    from sqlalchemy import select

    from auth.deps import user_has_permission
    from models.announcement import Announcement
    from models.competition import Competition
    from realtime import manager, register_room_type
    from routers.announcements import router as announcements_router
    from models.challenge import Challenge
    from routers.announcements import clarifications_router
    from utils.announcements import (
        clarifiable,
        hidden_clarification_challenges,
        scrub_withdrawn_answer,
        shown_body,
        resolve_recipients,
        user_team_ids,
        visible_to_user,
    )
    from utils.notifications import broadcast_notifications, create_notifications

    app.include_router(announcements_router)
    app.include_router(clarifications_router)

    def _frame(a: Announcement, *, staff: bool = False) -> dict:
        return {
            "id": a.id,
            "competition_id": a.competition_id,
            "title": a.title,
            "severity": a.severity,
            "audience_type": a.audience_type,
            "created_at": a.created_at.isoformat(),
            # A clarification (#450): which challenge, and the question it
            # answers — so the challenge's page can list it live.
            "kind": a.kind,
            "challenge_id": a.challenge_id,
            "question": a.question,
            # A withdrawn clarification travels without its answer — the
            # shared room is everyone; a staff member's own snapshot keeps it.
            "withdrawn_at": a.withdrawn_at.isoformat() if a.withdrawn_at else None,
            "body": shown_body(a, staff=staff),
        }

    async def _recent(db, user, competition_id: str) -> list[dict]:
        rows = list(
            (
                await db.execute(
                    select(Announcement)
                    .where(
                        Announcement.competition_id == competition_id,
                        # The live feed is published-only — a scheduled draft
                        # (#349) must not ride the reconnect snapshot, or it would
                        # surface before its publish_at.
                        Announcement.hidden.is_(False),
                    )
                    .order_by(Announcement.created_at.desc())
                    .limit(RECENT_LIMIT)
                )
            ).scalars()
        )
        # Same audience gate as the REST read — a snapshot must not hand a
        # reconnecting client an announcement it was never targeted with.
        is_staff = await user_has_permission(
            db, user.id, "announcement_create", competition_id
        )
        if not is_staff:
            team_ids = await user_team_ids(db, competition_id, user.id)
            hidden = await hidden_clarification_challenges(db, competition_id, rows)
            rows = [
                a
                for a in rows
                if visible_to_user(
                    a, user_id=user.id, team_ids=team_ids, is_staff=False
                )
                and a.challenge_id not in hidden
            ]
        return [_frame(a, staff=is_staff) for a in rows]

    async def authorize(db, user, competition_id: str) -> bool:
        if await db.get(Competition, competition_id) is None:
            return False
        return await user_has_permission(
            db, user.id, "challenge_view", competition_id
        )

    async def snapshot(db, user, competition_id: str) -> dict:
        return {
            "type": "announcements",
            "competition_id": competition_id,
            "announcements": await _recent(db, user, competition_id),
        }

    register_room_type("announcements", authorize=authorize, snapshot=snapshot)

    # Background lane (#176, ADR-0012): fan-out is per-recipient row creation +
    # WS sends, which for an all-participants announcement was a 24s foreground
    # block on the POST. The Announcement row itself is committed by the route
    # before this event is emitted, so it stays durable; only the per-user
    # notification rows + WS delivery are deferred (best-effort, ms later).
    @event_bus.on(
        "announcement.published",
        owner="announcements",
        background=True,
        timeout=DELIVER_HANDLER_TIMEOUT,
    )
    async def deliver_announcement(event_name: str, payload: dict) -> None:
        await _fan_out(payload, withdrawn=False)

    # A withdrawn clarification (#450 follow-up) is delivered like the
    # original: the room updates it in place and everyone gets a bell notice,
    # through the same batched fan-out (and so the same time budget).
    @event_bus.on(
        "announcement.withdrawn",
        owner="announcements",
        background=True,
        timeout=DELIVER_HANDLER_TIMEOUT,
    )
    async def deliver_withdrawal(event_name: str, payload: dict) -> None:
        await _fan_out(payload, withdrawn=True)

    async def _fan_out(payload: dict, *, withdrawn: bool) -> None:
        competition_id = payload.get("competition_id")
        announcement_id = payload.get("announcement_id")
        if not competition_id or not announcement_id:
            return

        async with db_factory() as db:
            announcement = await db.get(Announcement, announcement_id)
            if announcement is None:
                return
            # Sorted so batching is deterministic: a partial delivery is then
            # reproducible rather than depending on set iteration order.
            recipients = sorted(await resolve_recipients(db, announcement))
            targeted = announcement.audience_type != "all"
            frame = {
                "type": "announcement_withdrawn" if withdrawn else "announcement",
                "announcement": _frame(announcement),
            }
            # A critical announcement overrides a muted in-app category — the
            # one sanctioned bypass (§4.4), because the operator is saying
            # something the competition can't afford to miss.
            notification_type = f"announcement.{announcement.severity}"
            title = announcement.title
            body = announcement.body
            force = announcement.severity == "critical"
            link = None
            if announcement.kind == "clarification":
                # Same mute category (announcement.*), its own chip in the
                # bell, and a link to the challenge it's about: a programming
                # problem has its own page, a flag challenge opens from the
                # board.
                notification_type = "announcement.clarification"
                challenge = (
                    await db.get(Challenge, announcement.challenge_id)
                    if announcement.challenge_id
                    else None
                )
                if challenge is not None and challenge.flag_type == "programming":
                    link = f"/challenges/{challenge.id}"
                elif challenge is not None:
                    link = "/challenges"
                if withdrawn:
                    competition = await db.get(Competition, competition_id)
                    if (
                        challenge is None
                        or competition is None
                        or not clarifiable(competition, challenge)
                    ):
                        # Competitors can't see the challenge (or play is
                        # closed), so they can't see the clarification either:
                        # no one to tell — the feed shows it withdrawn if the
                        # challenge comes back.
                        return
                    notification_type = "announcement.clarification_withdrawn"
                    body = WITHDRAWN_NOTICE

        # The shared-room frame goes first and carries the announcement inline,
        # and the row it describes was committed by the route before this event
        # was emitted — so there is nothing uncommitted for it to expose. Doing
        # it ahead of the fan-out means the live banner survives even if
        # delivery is later cancelled. (The ordering that does matter — never
        # pushing a notification frame for an uncommitted row — is preserved
        # per batch below.)
        if not targeted:
            await manager.broadcast("announcements", competition_id, frame)

        # Fan out in committed batches (#454): each batch is durable and
        # delivered before the next starts, so a cancelled handler loses only
        # the recipients it never reached.
        for start in range(0, len(recipients), FANOUT_BATCH):
            batch = recipients[start : start + FANOUT_BATCH]
            async with db_factory() as db:
                # A clarification withdrawn mid-delivery (#450): stop — the
                # withdrawal notifies everyone itself.
                if not withdrawn and await _withdrawn(db, announcement_id):
                    return
                notifications = await create_notifications(
                    db,
                    batch,
                    type=notification_type,
                    title=title,
                    body=body,
                    competition_id=competition_id,
                    force=force,
                    link=link,
                    announcement_id=announcement_id,
                )
                await db.commit()
            # Targeted announcements ride the per-user notification rooms only;
            # the recipient's client turns that frame into a refetch of its
            # filtered list.
            await broadcast_notifications(notifications)
            if not withdrawn:
                async with db_factory() as db:
                    # Withdrawn between that check and this batch's commit:
                    # take the answer back out of what was just written.
                    if await _withdrawn(db, announcement_id):
                        await scrub_withdrawn_answer(db, announcement_id)
                        await db.commit()
                        return

    async def _withdrawn(db, announcement_id: str) -> bool:
        return (
            await db.scalar(
                select(Announcement.withdrawn_at).where(Announcement.id == announcement_id)
            )
        ) is not None
