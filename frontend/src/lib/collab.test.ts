import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as Y from "yjs";

import { base64ToBytes, bindCollabDoc, bytesToBase64, MAX_SYNC_BYTES } from "@/lib/collab";
import { openRoomSocket, type RoomSocketStatus } from "@/lib/ws";

vi.mock("@/lib/ws", () => ({ openRoomSocket: vi.fn() }));

describe("base64 <-> bytes", () => {
  it("round-trips arbitrary binary, including high bytes and zeros", () => {
    const bytes = new Uint8Array([0, 1, 2, 127, 128, 200, 255, 0, 42]);
    expect(base64ToBytes(bytesToBase64(bytes))).toEqual(bytes);
  });

  it("round-trips an empty payload", () => {
    expect(base64ToBytes(bytesToBase64(new Uint8Array()))).toEqual(new Uint8Array());
  });
});

describe("Y.js updates survive the base64 transport and converge", () => {
  // Simulates the relay: whatever bytes one doc emits are base64-encoded (as they
  // are on the wire), decoded on the far side, and applied — proving the encode
  // helpers preserve updates well enough for CRDT convergence (ADR-0014).
  const relay = (from: Y.Doc, to: Y.Doc) => {
    from.on("update", (update: Uint8Array) => {
      Y.applyUpdate(to, base64ToBytes(bytesToBase64(update)));
    });
  };

  it("merges concurrent edits from two clients into the same document", () => {
    const a = new Y.Doc();
    const b = new Y.Doc();
    relay(a, b);
    relay(b, a);

    // Two clients type into the shared text concurrently.
    a.getText("notes").insert(0, "hello ");
    b.getText("notes").insert(b.getText("notes").length, "world");

    // Both converge to identical content, no lost writes.
    expect(a.getText("notes").toString()).toBe(b.getText("notes").toString());
    expect(a.getText("notes").toString()).toContain("hello");
    expect(a.getText("notes").toString()).toContain("world");
  });

  it("a fresh client reconstructs from a full-state snapshot", () => {
    const source = new Y.Doc();
    source.getText("notes").insert(0, "persisted content");
    // encodeStateAsUpdate is exactly what the client sends as note_persist and
    // the server hands back as note_snapshot.
    const snapshot = bytesToBase64(Y.encodeStateAsUpdate(source));

    const fresh = new Y.Doc();
    Y.applyUpdate(fresh, base64ToBytes(snapshot));
    expect(fresh.getText("notes").toString()).toBe("persisted content");
  });
});

describe("bindCollabDoc", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  /** Bind `doc` to a stand-in socket: records what's sent, drives the status. */
  function bind(doc: Y.Doc) {
    const sent: { type: string; update?: string; state?: string }[] = [];
    let onStatus: (status: RoomSocketStatus) => void = () => {};
    vi.mocked(openRoomSocket).mockImplementation((_type, _id, opts) => {
      onStatus = opts.onStatus ?? onStatus;
      return { send: (data) => sent.push(data as (typeof sent)[number]), close: vi.fn() };
    });
    const onTooLarge = vi.fn();
    const handle = bindCollabDoc(doc, "team_challenge:t:c", { onTooLarge });
    return { sent, setStatus: (status: RoomSocketStatus) => onStatus(status), onTooLarge, handle };
  }

  it("sends nothing while the socket is down; the full state on open carries it", () => {
    const doc = new Y.Doc();
    const { sent, setStatus, handle } = bind(doc);
    doc.getText("notes").insert(0, "typed offline");
    expect(sent).toEqual([]);

    setStatus("open");
    expect(sent.map((f) => f.type)).toEqual(["note_update"]);
    const peer = new Y.Doc();
    Y.applyUpdate(peer, base64ToBytes(sent[0].update!));
    expect(peer.getText("notes").toString()).toBe("typed offline");

    setStatus("closed");
    doc.getText("notes").insert(0, "more ");
    expect(sent).toHaveLength(1);
    handle.close();
  });

  it("never sends more than the server accepts, and says when the note is too large", () => {
    const doc = new Y.Doc();
    const { sent, setStatus, onTooLarge, handle } = bind(doc);
    setStatus("open");
    sent.length = 0;

    const text = doc.getText("notes");
    text.insert(0, "x".repeat(MAX_SYNC_BYTES + 1));
    expect(sent).toEqual([]);
    expect(onTooLarge).toHaveBeenLastCalledWith(true);
    setStatus("closed");
    setStatus("open"); // a reconnect doesn't re-send it either
    expect(sent).toEqual([]);

    text.delete(0, text.length); // back under the cap
    vi.advanceTimersByTime(2_000); // the debounced persist
    expect(sent.map((f) => f.type)).toEqual(["note_update", "note_persist"]);
    expect(onTooLarge).toHaveBeenLastCalledWith(false);
    handle.close();
  });
});
