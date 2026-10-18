// CRDT transport binding (ARCHITECTURE.md §4.2, ADR-0014).
//
// Binds a Y.js document to a `note/<docKey>` room over the §4.1 WebSocket layer.
// The server is a dumb relay (ADR-0014): it never decodes the doc. This module
// speaks the three-frame protocol the `collab` backend module expects, encoding
// binary Y updates as base64 to ride the JSON socket:
//
// - server → us on join: `note_snapshot` — apply the persisted state.
// - us → server on local edit: `note_update` — relayed to other clients live.
// - us → server debounced: `note_persist` — the full merged state, stored.
//
// Convergence itself is Y.js's job on the clients; we only move bytes.

import * as Y from "yjs";

import { openRoomSocket, type RoomSocketStatus } from "@/lib/ws";

// Origin tag marking updates we applied *from* the network, so our own
// doc-update handler doesn't echo them straight back out.
const REMOTE = Symbol("collab-remote");

const PERSIST_DEBOUNCE_MS = 1_500;

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

export function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

export interface CollabHandle {
  close: () => void;
}

/** The server's cap on a note's state (backend `plugins/collab`
 *  MAX_STATE_BYTES): it drops a bigger update or persist, and refuses a
 *  WebSocket frame much past it outright (closing 1009) — which a full-state
 *  re-send on every reconnect would turn into a loop. So nothing over it is
 *  ever sent; the note reports that it's too large to sync instead. */
export const MAX_SYNC_BYTES = 1_048_576;

/** Wire `doc` to the note room for `docKey`. Returns a handle; call `close()`
 *  on unmount (it flushes a final persist, unbinds, and closes the socket). */
export function bindCollabDoc(
  doc: Y.Doc,
  docKey: string,
  opts: {
    onStatus?: (status: RoomSocketStatus) => void;
    /** Whether the note has outgrown what the server will sync or store. */
    onTooLarge?: (tooLarge: boolean) => void;
  } = {},
): CollabHandle {
  let persistTimer: ReturnType<typeof setTimeout> | null = null;
  // Only an authed socket is sent to. Edits made while it's down aren't queued
  // — the full state sent on the next "open" carries them, and a backlog of
  // per-keystroke updates replayed first could trip the server's rate limit.
  let live = false;
  let tooLarge = false;

  function setTooLarge(value: boolean) {
    if (value === tooLarge) return;
    tooLarge = value;
    opts.onTooLarge?.(value);
  }

  /** Send the full merged state as `note_update` (peers merge it) or
   *  `note_persist` (the server stores it) — unless it's over the cap. */
  function sendFullState(type: "note_update" | "note_persist") {
    const state = Y.encodeStateAsUpdate(doc);
    setTooLarge(state.length > MAX_SYNC_BYTES);
    if (tooLarge) return;
    const encoded = bytesToBase64(state);
    socket.send(type === "note_update" ? { type, update: encoded } : { type, state: encoded });
  }

  function schedulePersist() {
    if (persistTimer) clearTimeout(persistTimer);
    persistTimer = setTimeout(() => {
      if (live) sendFullState("note_persist");
    }, PERSIST_DEBOUNCE_MS);
  }

  const socket = openRoomSocket("note", docKey, {
    mode: "edit",
    onStatus: (status) => {
      live = status === "open";
      opts.onStatus?.(status);
      if (live) {
        // On (re)connect, push our full state so peers merge our content and the
        // server persists any edits made while we were disconnected.
        sendFullState("note_update");
        schedulePersist();
      }
    },
    onMessage: (data) => {
      const frame = data as { type?: string; update?: string | null };
      if (
        (frame.type === "note_snapshot" || frame.type === "note_update") &&
        frame.update
      ) {
        Y.applyUpdate(doc, base64ToBytes(frame.update), REMOTE);
      }
    },
  });

  const onUpdate = (update: Uint8Array, origin: unknown) => {
    if (origin === REMOTE) return; // applied from the network — don't re-send
    if (!live) return; // the full state on reconnect carries it
    if (update.length > MAX_SYNC_BYTES) {
      setTooLarge(true);
      return;
    }
    socket.send({ type: "note_update", update: bytesToBase64(update) });
    schedulePersist();
  };
  doc.on("update", onUpdate);

  return {
    close() {
      if (persistTimer) clearTimeout(persistTimer);
      // Best-effort final persist so the last keystrokes survive the unmount.
      if (live) sendFullState("note_persist");
      doc.off("update", onUpdate);
      socket.close();
    },
  };
}
