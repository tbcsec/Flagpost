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
    from utils.scoreboard import compute_scoreboard

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
        board = await compute_scoreboard(db, competition)
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

    # A solve changes totals; a hint reveal deducts its cost; a score adjustment
    # (§5.3 update_score) or an award (create_award / manual awards) adds/removes
    # points; and a freeze/unfreeze switches between the live and frozen board —
    # all of these move what the board shows, so each triggers a recompute +
    # live broadcast (which serves the frozen snapshot while a freeze is on).
    for _event in (
        "challenge.solved",
        "challenge.hint_requested",
        "score.adjusted",
        "achievement.awarded",
        "scoreboard.frozen",
        "scoreboard.unfrozen",
    ):
        event_bus.subscribe(_event, broadcast_scoreboard, owner="scoring")
