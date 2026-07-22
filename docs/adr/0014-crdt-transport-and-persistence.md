# ADR-0014: CRDT transport as a dumb relay + client-snapshot persistence

**Status:** Accepted
**Date:** 2026-07-22
**Architecture reference:** `ARCHITECTURE.md` §4.2 (collaborative editing), §4.1
(real-time layer)

## Context

Tier 3 Phase 7 adds real collaborative editing (§4.2): a team's per-challenge
scratchpad and staff internal notes on a ticket, both prose fields edited by
several people at once. The chosen CRDT is Y.js under TipTap (already the editor,
§2). The open question was **what the server does with the Y.js document** —
because Y.js needs *some* server to relay updates between clients and to persist
the document between sessions.

The real options:

1. **Server-side Y.js engine.** Run a Y document on the backend (`y-py`, the
   Rust/`Yrs` Python binding) that merges updates authoritatively, à la
   `ypy-websocket`. Gives the server a true merged state and lets it compact the
   update log itself.
2. **Dumb relay + client-snapshot persistence.** The server treats the document
   as opaque bytes: it relays Y update frames between clients in a room and
   stores a single full-state blob that clients push on a debounce
   (`Y.encodeStateAsUpdate`). It never decodes the CRDT.
3. **A separate Node y-websocket sidecar.** The canonical y-websocket server,
   run as its own process next to the Python backend.

Constraints that decided it: the backend is **single-process** (like the event
bus, ADR-0005) and **async Python**; the test stack is **SQLite with no native
deps** (ADR-0006); and the existing `/ws/<type>/<id>` room layer (§4.1) already
does first-frame auth, per-room authorization, and fan-out. Option 1 pulls a
Rust-native wheel into that test stack and a second CRDT implementation to keep
in step with the JS one. Option 3 adds a whole second runtime and a second auth
surface. Both are heavy for two prose fields at CTF-team scale (a few people per
document).

## Decision

Go with **option 2**: the `note/<doc_key>` room is a dumb relay. The server
relays `note_update` frames to the *other* members of a room (never decoding
them) and persists one opaque blob per document — the full merged state a client
last sent as `note_persist`, handed back to a fresh client as the join
`note_snapshot`. Convergence is Y.js's job on the clients; the server only moves
and stores bytes. Who may read/write a note is resolved per-request server-side
(`utils/collab.resolve_note`), exactly like a REST route (§7.6) — the transport
stays agnostic to which side of the platform it serves (§4.2). Binary rides the
JSON socket as base64.

## Consequences

- **Positive:** no native dependency and no second runtime — the SQLite test
  stack and single-process model hold. Reuses the §4.1 room verbatim (auth,
  authorization, fan-out); the only additions are an `on_message` hook and a
  `broadcast(exclude=…)`. Persistence is a single row per doc — bounded storage,
  no update-log compaction problem. The server can't leak document structure it
  never decodes.
- **Negative / cost:** the server holds no authoritative merged state, so
  "latest full snapshot wins" for the stored blob — correct because every live
  client is converged via the relay, but it does mean persistence relies on a
  client sending `note_persist` (debounced + on close/reconnect); a client that
  edits and is hard-killed before the debounce fires can lose its most recent
  keystrokes from the *stored* copy (other live clients still have them). No
  server-side history/versioning. base64 over JSON is ~33% larger than a binary
  frame.
- **Forecloses:** nothing permanently. If server-authoritative merging, document
  history, or cross-process fan-out is needed later, `y-py` (or Redis pub/sub
  behind the same room interface, the §4.1 scaling seam) can replace the relay
  without changing the client protocol or the `collab_documents` store shape.
