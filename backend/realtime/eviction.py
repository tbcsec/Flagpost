"""Server-driven WebSocket revocation (#10).

Room authorization runs once, at the handshake — so a socket a user already holds
survives when their access is revoked mid-session (a soft-ban, an account
deletion, or removal from a team). These listeners close the affected sockets
when the corresponding events fire, restoring the bound the handshake ban-check
only promises for *new* connections. Registered on the background lane (ADR-0012):
the work is a socket close, never a DB touch, and must not block the emitting
request.

Eviction reaches **every worker** (GHSA-p679). These handlers run only on the
worker that emitted the event — the bus is per-process — so the manager
publishes each eviction through the cross-worker relay; before that, a revoked
user kept every socket held on any other worker, indefinitely. It also marks the
target sockets revoked *before* awaiting any close, so neither a stalled close
nor this background handler being cut off at the bus timeout can leave access
in place: at worst a TCP close is abandoned on a socket that already receives
nothing and is refused when it sends.
"""

from __future__ import annotations

import logging

from realtime.manager import manager

logger = logging.getLogger("realtime")


def register_ws_eviction(event_bus) -> None:
    async def _on_user_revoked(event_name: str, payload: dict) -> None:
        user_id = payload.get("user_id")
        if not user_id:
            return
        closed = await manager.close_user_sockets(user_id)
        if closed:
            logger.info("evicted %d websocket(s) for user %s", closed, user_id)

    async def _on_team_member_left(event_name: str, payload: dict) -> None:
        user_id = payload.get("user_id")
        team_id = payload.get("team_id")
        if not user_id or not team_id:
            return
        # Only the removed team's scratchpad docs (doc_key team_challenge:<team_id>:*);
        # the member keeps their other rooms (scoreboard, tickets, other teams).
        await manager.close_user_sockets(
            user_id,
            room_type="note",
            room_id_prefix=f"team_challenge:{team_id}:",
        )

    async def _evict(subject_user_id: str, why: str) -> None:
        closed = await manager.close_user_sockets(subject_user_id)
        if closed:
            logger.info(
                "evicted %d websocket(s) for user %s (%s)", closed, subject_user_id, why
            )

    async def _on_role_unassigned(event_name: str, payload: dict) -> None:
        # Room authz is handshake-only, so unassigning a role mid-session leaves
        # the user's open sockets in staff-only rooms (e.g. ticket internal notes)
        # until the socket closes (security F4). Force a re-handshake. NOTE: the
        # demoted user is `subject_user_id`; `user_id` is the acting admin.
        subject = payload.get("subject_user_id")
        if subject:
            await _evict(subject, "role unassigned")

    async def _on_role_updated(event_name: str, payload: dict) -> None:
        # A custom role's permission set changed: every current holder's effective
        # access may have shrunk, so re-handshake them all. `affected_user_ids` is
        # present only when permissions (not just name/description) changed, so a
        # cosmetic edit doesn't churn every holder's sockets.
        #
        # One call for all holders, not a loop of per-user evictions: the old
        # sequential loop awaited each close in turn, so one stalled peer could
        # run it past the bus timeout and leave every later holder un-evicted
        # (GHSA-p679). evict_users marks them all revoked before awaiting
        # anything, then closes concurrently.
        subjects = payload.get("affected_user_ids") or []
        if not subjects:
            return
        closed = await manager.evict_users(subjects)
        if closed:
            logger.info(
                "evicted %d websocket(s) across %d holder(s) (role permissions changed)",
                closed,
                len(subjects),
            )

    event_bus.subscribe("user.banned", _on_user_revoked, background=True)
    event_bus.subscribe("user.deleted", _on_user_revoked, background=True)
    event_bus.subscribe("team.member_left", _on_team_member_left, background=True)
    # Mid-session privilege revocation (F4). role.deleted needs no handler: a role
    # can't be deleted while still assigned (delete_role 409s), so its holders were
    # already unassigned — and evicted — one role.unassigned at a time.
    event_bus.subscribe("role.unassigned", _on_role_unassigned, background=True)
    event_bus.subscribe("role.updated", _on_role_updated, background=True)
