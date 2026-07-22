"""Collaborative Notes module (ARCHITECTURE.md §4.2, ADR-0014).

Owns the ``note/<doc_key>`` WebSocket room — the CRDT collaboration transport
shared by both sides of the platform (team challenge scratchpad, staff ticket
notes). The room is a **dumb relay** (ADR-0014): it never decodes the Y.js
document. Three frame kinds ride the socket after auth:

- server → client on join: ``{"type": "note_snapshot", "update": <b64|null>}`` —
  the last-persisted merged state so a fresh client can reconstruct the doc.
- client → server on local edit: ``{"type": "note_update", "update": <b64>}`` —
  relayed to every *other* member of the room (live convergence), no DB touch.
- client → server debounced: ``{"type": "note_persist", "state": <b64>}`` — the
  full merged state, upserted as the single stored blob for the doc.

*Who* may join/read/write a note is decided per-request by ``utils.collab``
(team membership for a scratchpad; ``ticket_view_internal_notes`` for a ticket),
never here — the transport stays agnostic to which side it serves (§4.2).
"""

from __future__ import annotations

import base64
import binascii
import logging

# A collaborative note is prose, not a data dump; cap the persisted blob so a
# client can't push an unbounded payload into the store.
MAX_STATE_BYTES = 1_048_576  # 1 MiB

logger = logging.getLogger("collab")


def setup(app, event_bus, db_factory) -> None:
    from db import SessionLocal
    from realtime import manager, register_room_type
    from utils.collab import load_state, resolve_note, save_state

    async def authorize_note(db, user, doc_key: str) -> bool:
        return await resolve_note(db, user, doc_key) is not None

    async def note_snapshot(db, user, doc_key: str) -> dict | None:
        state = await load_state(db, doc_key)
        return {
            "type": "note_snapshot",
            "update": base64.b64encode(state).decode() if state else None,
        }

    async def on_note_message(user, room_type: str, doc_key: str, websocket, frame) -> None:
        kind = frame.get("type")
        if kind == "note_update":
            update = frame.get("update")
            if isinstance(update, str):
                # Relay only — no DB, no decode. Exclude the sender so a client
                # never receives an echo of its own update (§4.2).
                await manager.broadcast(
                    room_type,
                    doc_key,
                    {"type": "note_update", "update": update},
                    exclude=websocket,
                )
        elif kind == "note_persist":
            state_b64 = frame.get("state")
            if not isinstance(state_b64, str):
                return
            try:
                raw = base64.b64decode(state_b64, validate=True)
            except (binascii.Error, ValueError):
                return
            if not raw or len(raw) > MAX_STATE_BYTES:
                return
            # Re-authorize on the write path (defense in depth) and resolve the
            # owning competition for the row's tenant scope (§6.2).
            async with SessionLocal() as db:
                resolved = await resolve_note(db, user, doc_key)
                if resolved is None:
                    return
                await save_state(db, doc_key, resolved.competition_id, raw)

    register_room_type(
        "note",
        authorize=authorize_note,
        snapshot=note_snapshot,
        on_message=on_note_message,
    )
