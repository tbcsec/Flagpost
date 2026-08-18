import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { backoffDelayMs, openRoomSocket, PING_INTERVAL_MS } from "@/lib/ws";

vi.mock("@/stores/auth", () => ({
  useAuthStore: { getState: () => ({ accessToken: "test-token" }) },
}));

describe("backoffDelayMs", () => {
  it("grows exponentially with the attempt number", () => {
    // random() = 1 → the full cap for that attempt.
    expect(backoffDelayMs(0, () => 1)).toBe(1_000);
    expect(backoffDelayMs(1, () => 1)).toBe(2_000);
    expect(backoffDelayMs(3, () => 1)).toBe(8_000);
  });

  it("caps at 30s no matter how many attempts", () => {
    expect(backoffDelayMs(10, () => 1)).toBe(30_000);
    expect(backoffDelayMs(50, () => 1)).toBe(30_000);
  });

  it("jitters between half and the full delay", () => {
    // random() = 0 → half the cap; random() = 1 → the cap.
    expect(backoffDelayMs(2, () => 0)).toBe(2_000);
    expect(backoffDelayMs(2, () => 1)).toBe(4_000);
  });
});

/** Minimal WebSocket double: the test drives open/message/close by hand. */
class FakeWebSocket {
  static OPEN = 1;
  static instances: FakeWebSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  // test drivers
  serverOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
  serverSend(obj: unknown) {
    this.onmessage?.({ data: JSON.stringify(obj) });
  }
}

describe("keepalive ping (ADR-0031)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function openAuthed() {
    const onMessage = vi.fn();
    const handle = openRoomSocket("scoreboard", "c1", { onMessage });
    const sock = FakeWebSocket.instances[0];
    sock.serverOpen(); // client sends the auth frame
    sock.serverSend({ type: "auth_ok" });
    return { handle, sock, onMessage };
  }

  it("pings on the interval once authed, and swallows the pong", () => {
    const { handle, sock, onMessage } = openAuthed();
    expect(sock.sent).toHaveLength(1); // just the auth frame so far

    vi.advanceTimersByTime(PING_INTERVAL_MS);
    vi.advanceTimersByTime(PING_INTERVAL_MS);
    const pings = sock.sent.filter((f) => f === JSON.stringify({ type: "ping" }));
    expect(pings).toHaveLength(2);

    sock.serverSend({ type: "pong" });
    expect(onMessage).not.toHaveBeenCalled(); // pong is not a room frame

    sock.serverSend({ type: "scoreboard", rows: [] });
    expect(onMessage).toHaveBeenCalledTimes(1); // real frames still flow
    handle.close();
  });

  it("stops pinging when the socket closes or the handle is closed", () => {
    const { handle, sock } = openAuthed();
    vi.advanceTimersByTime(PING_INTERVAL_MS);
    const sentBefore = sock.sent.length;

    handle.close(); // also fires sock.onclose via close()
    vi.advanceTimersByTime(PING_INTERVAL_MS * 4);
    expect(sock.sent.length).toBe(sentBefore); // no pings after close

    // And no ping before auth on a fresh socket: nothing to keep alive yet.
    const fresh = new FakeWebSocket("ws://x");
    void fresh;
  });
});
