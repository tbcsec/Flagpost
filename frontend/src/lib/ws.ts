// Room WebSocket client (ARCHITECTURE.md §4.1).
//
// Mirrors the server contract in backend/realtime: connect to
// /ws/<room_type>/<room_id>, send the access token as the FIRST frame (never
// in the URL — ADR-0003), then receive JSON broadcast frames. Reconnects with
// capped exponential backoff + jitter so a dropped connection doesn't hammer
// the server in a reconnect storm.

import { useAuthStore } from "@/stores/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** The ws(s):// base for room sockets. An **empty** NEXT_PUBLIC_API_URL means
 *  same-origin mode (the versioned release images bake this): the API is
 *  reached with relative paths behind a single-origin proxy, so the socket
 *  base derives from the page's own origin at connect time. Relative URLs in
 *  `new WebSocket()` aren't reliable across browsers, hence the explicit
 *  derivation rather than letting `""` fall through. */
function wsBase(): string {
  const base =
    API_URL || (typeof window !== "undefined" ? window.location.origin : "");
  return base.replace(/^http/, "ws");
}

export type RoomSocketStatus = "connecting" | "open" | "closed";

export interface RoomSocketHandle {
  close: () => void;
  /** Send a JSON frame once the socket is authed; buffered until then, and
   *  after a reconnect re-auths. Used by the CRDT relay (§4.2). */
  send: (data: unknown) => void;
}

interface RoomSocketOptions {
  onMessage: (data: unknown) => void;
  onStatus?: (status: RoomSocketStatus) => void;
  // Presence rooms (§4.1) read an optional view/edit mode off the auth frame.
  mode?: "view" | "edit";
}

const BASE_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;

/** App-level keepalive cadence (ADR-0031). Browsers can't send protocol-level
 *  WS pings, so an idle socket (a quiet scoreboard) has zero traffic and gets
 *  culled by proxy / load-balancer idle timeouts — default 60s on an AWS ALB —
 *  forcing pointless reconnect churn. 30s keeps even a default-configured LB's
 *  idle timer reset; the server answers `pong` (swallowed below). */
export const PING_INTERVAL_MS = 30_000;

/** Exponential backoff with full jitter, capped. Exported for tests. */
export function backoffDelayMs(attempt: number, random: () => number = Math.random): number {
  const capped = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** attempt);
  return Math.round(capped / 2 + random() * (capped / 2));
}

export function openRoomSocket(
  roomType: string,
  roomId: string,
  { onMessage, onStatus, mode }: RoomSocketOptions,
): RoomSocketHandle {
  const url = `${wsBase()}/ws/${roomType}/${roomId}`;
  let ws: WebSocket | null = null;
  let attempt = 0;
  let closed = false;
  let authed = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pingTimer: ReturnType<typeof setInterval> | null = null;
  // Frames requested before auth completes (or during a reconnect) wait here and
  // flush on auth_ok, so a caller never has to track connection state itself.
  const outbox: unknown[] = [];

  function flush() {
    if (!authed || ws?.readyState !== WebSocket.OPEN) return;
    while (outbox.length) ws.send(JSON.stringify(outbox.shift()));
  }

  // Keepalive pings are sent directly, NOT via the outbox — buffered pings
  // replayed after a reconnect would be stale noise. Started on auth_ok,
  // stopped whenever the socket drops.
  function stopPing() {
    if (pingTimer) {
      clearInterval(pingTimer);
      pingTimer = null;
    }
  }

  function startPing() {
    stopPing();
    pingTimer = setInterval(() => {
      if (authed && ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, PING_INTERVAL_MS);
  }

  function connect() {
    if (closed) return;
    onStatus?.("connecting");
    ws = new WebSocket(url);

    ws.onopen = () => {
      // First-frame auth: same access token as REST, never in the URL. Presence
      // rooms also carry the optional view/edit mode on this same frame (§4.1).
      const token = useAuthStore.getState().accessToken;
      ws?.send(JSON.stringify(mode ? { token, mode } : { token }));
    };

    ws.onmessage = (event) => {
      let data: unknown;
      try {
        data = JSON.parse(event.data as string);
      } catch {
        return; // non-JSON frame — ignore
      }
      const frame = data as { type?: string };
      if (frame.type === "auth_ok") {
        attempt = 0; // healthy connection: reset the backoff
        authed = true;
        startPing();
        onStatus?.("open");
        flush();
        return;
      }
      if (frame.type === "pong") return; // keepalive reply — not a room frame
      onMessage(data);
    };

    ws.onclose = () => {
      authed = false;
      stopPing();
      onStatus?.("closed");
      if (closed) return;
      timer = setTimeout(() => {
        attempt += 1;
        connect();
      }, backoffDelayMs(attempt));
    };

    // onclose fires after onerror; reconnect handling lives there.
    ws.onerror = () => {};
  }

  connect();

  return {
    close() {
      closed = true;
      if (timer) clearTimeout(timer);
      stopPing();
      ws?.close();
    },
    send(data: unknown) {
      outbox.push(data);
      flush();
    },
  };
}
