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
    import hashlib
    import json
    from datetime import datetime

    from auth.deps import user_has_permission
    from db import ensure_aware_utc
    from models.competition import Competition
    from realtime import manager, register_room_type
    from routers.public_scoreboard import router as public_router
    from routers.scoreboard import router as scoreboard_router
    from utils.scoreboard import (
        cached_scoreboard,
        compute_scoreboard,
        freeze_cutoff,
        invalidate_scoreboard,
    )
    from utils.scoreboard_timeline import invalidate_timeline

    app.include_router(scoreboard_router)
    # The unauthenticated spectator board for public competitions (Phase 9).
    app.include_router(public_router)

    from utils.competition_status import has_started

    async def authorize(db, user, competition_id: str) -> bool:
        # Same gate as the REST /scoreboard route (§7.6): the competition exists,
        # the caller has competitor access, AND it has started — the #221 gate
        # (GHSA-r7j2). REST require_started 403s a not_started board for
        # competitors, so the WS room must match, or a Participant could snapshot
        # the pre-start board (staff test-solve totals) the REST route refuses.
        # Staff (challenge_edit) are exempt, exactly as require_started is.
        competition = await db.get(Competition, competition_id)
        if competition is None:
            return False
        if not await user_has_permission(
            db, user.id, "challenge_view", competition_id
        ):
            return False
        if has_started(competition):
            return True
        return await user_has_permission(db, user.id, "challenge_edit", competition_id)

    async def snapshot(db, user, competition_id: str) -> dict:
        competition = await db.get(Competition, competition_id)
        # Cached read model (#87): a reconnect herd computes the board once, not
        # once per joining socket.
        board = await cached_scoreboard(db, competition)
        return {"type": "scoreboard", **board}

    register_room_type("scoreboard", authorize=authorize, snapshot=snapshot)

    # Freeze containment (GHSA-r7j2): while the board is frozen, a frame sent
    # on a post-cutoff event is timed to that event whatever it carries — and
    # comparing boards can't rule that out, because the frozen board also moves
    # with no event of its own (a team renamed, a team created), which the next
    # post-cutoff solve would then carry out. So while frozen the room decides
    # from the triggering event: a freeze/unfreeze always goes out; a solve, or
    # a revoked solve, only when that solve is dated at or before the cutoff (a
    # backdated judge verdict, a rejudge of a pre-cutoff solve); hint costs,
    # adjustments and awards are stamped when they happen — after the cutoff —
    # so never. Staff read the live board over REST (``?live=true``).
    def _moves_frozen_board(event_name: str, payload: dict, cutoff) -> bool:
        if event_name in ("scoreboard.frozen", "scoreboard.unfrozen"):
            return True
        if event_name in ("challenge.solved", "challenge.solve_revoked"):
            try:
                solved_at = ensure_aware_utc(
                    datetime.fromisoformat(payload["solved_at"])
                )
            except (KeyError, TypeError, ValueError):
                return False  # no usable solve time: fail closed
            return solved_at <= cutoff
        return False

    # The frozen board last sent, per competition, so an event that passes the
    # gate but leaves the board as it was sends nothing.
    held: dict[str, str] = {}

    def _digest(board: dict) -> str:
        return hashlib.sha256(
            json.dumps(board, sort_keys=True, default=str).encode()
        ).hexdigest()

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
            cutoff = freeze_cutoff(competition)
            if cutoff is not None and not _moves_frozen_board(
                event_name, payload, cutoff
            ):
                return
            board = await compute_scoreboard(db, competition)
        if not board["frozen"]:
            held.pop(competition_id, None)
        else:
            digest = _digest(board)
            if held.get(competition_id) == digest:
                return
            held[competition_id] = digest
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
        "challenge.solve_revoked",  # a rejudge/override took a solve back (#450)
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
