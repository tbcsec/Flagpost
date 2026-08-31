"""Scoring & Scoreboard module (ROADMAP #13, §11.3 required-core).

Owns the competitor-facing scoreboard on top of the submissions data the
challenges module records:

- the REST endpoint for initial load,
- the "scoreboard" WebSocket room type (authorized exactly like the REST
  route — ``challenge_view`` on the competition — with the current board as
  the join snapshot), and
- the listeners that recompute and broadcast the board to the competition's
  room whenever totals move. Handlers stay fast (one aggregate query +
  in-process fan-out), run on the foreground lane (ADR-0012 default), and
  skip the recompute entirely when nobody is watching.
"""

from __future__ import annotations


def setup(app, event_bus, db_factory) -> None:
    from auth.deps import user_has_permission
    from models.competition import Competition
    from realtime import manager, register_room_type
    from routers.public_scoreboard import router as public_router
    from routers.scoreboard import router as scoreboard_router
    from utils.scoreboard import (
        cached_scoreboard,
        compute_scoreboard,
        invalidate_scoreboard,
    )
    from utils.scoreboard_timeline import invalidate_timeline

    app.include_router(scoreboard_router)
    # The unauthenticated spectator board for public competitions (Phase 9).
    app.include_router(public_router)

    async def authorize(db, user, competition_id: str) -> bool:
        # Same gate as the REST route (§7.6): competitor access to the
        # competition. Also requires the competition to actually exist so a
        # global admin token can't park sockets in rooms for made-up ids.
        if await db.get(Competition, competition_id) is None:
            return False
        return await user_has_permission(
            db, user.id, "challenge_view", competition_id
        )

    async def snapshot(db, user, competition_id: str) -> dict:
        competition = await db.get(Competition, competition_id)
        # Cached read model (#87): a reconnect herd computes the board once, not
        # once per joining socket.
        board = await cached_scoreboard(db, competition)
        return {"type": "scoreboard", **board}

    register_room_type("scoreboard", authorize=authorize, snapshot=snapshot)

    async def broadcast_scoreboard(event_name: str, payload: dict) -> None:
        competition_id = payload.get("competition_id")
        if not competition_id:
            return
        # No listeners → skip the recompute, not just the send.
        if manager.room_size("scoreboard", competition_id) == 0:
            return
        async with db_factory() as db:
            competition = await db.get(Competition, competition_id)
            if competition is None:
                return
            board = await compute_scoreboard(db, competition)
        await manager.broadcast(
            "scoreboard", competition_id, {"type": "scoreboard", **board}
        )

    async def invalidate_cache(event_name: str, payload: dict) -> None:
        competition_id = payload.get("competition_id")
        if competition_id:
            invalidate_scoreboard(competition_id)
            # The score-over-time chart (#348) is a second cached read of the
            # same data — drop it on exactly the same events so the chart can
            # never lag the table it sits beside.
            invalidate_timeline(competition_id)

    # What moves the *scoreboard WS room*: a solve changes totals, a hint reveal
    # deducts its cost, a score adjustment (§5.3 update_score) or award adds/
    # removes points, and a freeze/unfreeze switches between the live and frozen
    # board. These recompute + rebroadcast the shared board.
    scoring_events = (
        "challenge.solved",
        "challenge.hint_requested",
        "score.adjusted",
        "achievement.awarded",
        "scoreboard.frozen",
        "scoreboard.unfrozen",
    )
    # What invalidates the cached read model (#87): the scoring events above,
    # PLUS everything else that changes what a *read* of the board returns — a
    # subject appearing/disappearing (roster) or a challenge's value/existence
    # changing. Broader than the broadcast set so a cache hit only ever serves a
    # board that genuinely hasn't changed; the TTL is only a backstop for the
    # rare change with no event. Over-invalidating is a cheap dict delete.
    invalidating_events = scoring_events + (
        "competition.member_joined",  # individual-mode: a new participant row
        "team.created",  # team-mode: a new team row
        "team.deleted",  # a team row removed
        "challenge.updated",  # points / dynamic-scoring value edit
        "challenge.deleted",  # its solves stop counting
    )
    for _event in invalidating_events:
        # Foreground (a cheap dict delete, no room check) so the next reader —
        # and the background broadcast below — recomputes fresh.
        event_bus.subscribe(_event, invalidate_cache, owner="scoring")
    for _event in scoring_events:
        # Recompute + fan out on the background lane (#176, ADR-0012): the board
        # is a computed read model, not durable state, so this must not block
        # the mutation (a solve awaited the full recompute + broadcast before
        # responding).
        event_bus.subscribe(
            _event, broadcast_scoreboard, owner="scoring", background=True
        )
