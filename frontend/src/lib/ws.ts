// Room WebSocket client (ARCHITECTURE.md §4.1).
//
// Mirrors the server contract in backend/realtime: connect to
// /ws/<room_type>/<room_id>, send the access token as the FIRST frame (never
// in the URL — ADR-0003), then receive JSON broadcast frames. Reconnects with
// capped exponential backoff + jitter so a dropped connection doesn't hammer
// the server in a reconnect storm.

import { useAuthStore } from "@/stores/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type RoomSocketStatus = "connecting" | "open" | "closed";

export interface RoomSocketHandle {
  close: () => void;
}

interface RoomSocketOptions {
  onMessage: (data: unknown) => void;
  onStatus?: (status: RoomSocketStatus) => void;
}

const BASE_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;

/** Exponential backoff with full jitter, capped. Exported for tests. */
export function backoffDelayMs(attempt: number, random: () => number = Math.random): number {
  const capped = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** attempt);
  return Math.round(capped / 2 + random() * (capped / 2));
}

export function openRoomSocket(
  roomType: string,
  roomId: string,
  { onMessage, onStatus }: RoomSocketOptions,
): RoomSocketHandle {
  const url = `${API_URL.replace(/^http/, "ws")}/ws/${roomType}/${roomId}`;
  let ws: WebSocket | null = null;
  let attempt = 0;
  let closed = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  function connect() {
    if (closed) return;
    onStatus?.("connecting");
    ws = new WebSocket(url);

    ws.onopen = () => {
      // First-frame auth: same access token as REST, never in the URL.
      const token = useAuthStore.getState().accessToken;
      ws?.send(JSON.stringify({ token }));
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
        onStatus?.("open");
        return;
      }
      onMessage(data);
    };

    ws.onclose = () => {
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
      ws?.close();
    },
  };
}
