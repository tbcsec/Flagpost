import { describe, expect, it } from "vitest";
import * as Y from "yjs";

import { base64ToBytes, bytesToBase64 } from "@/lib/collab";

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
