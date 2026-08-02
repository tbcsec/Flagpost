import { beforeEach, describe, expect, it } from "vitest";

import { useChallengeViewStore } from "@/stores/challenge-view";

// jsdom 30 (under Node 26) no longer ships a working window.localStorage, so the
// test env provides none. Install a minimal in-memory stub — the store only uses
// getItem/setItem/removeItem/clear — so the persistence assertions have real
// storage to observe rather than the store's try/catch silently swallowing it.
class MemoryStorage {
  private store = new Map<string, string>();
  clear() {
    this.store.clear();
  }
  getItem(key: string) {
    return this.store.has(key) ? this.store.get(key)! : null;
  }
  setItem(key: string, value: string) {
    this.store.set(key, String(value));
  }
  removeItem(key: string) {
    this.store.delete(key);
  }
}

beforeEach(() => {
  Object.defineProperty(window, "localStorage", {
    value: new MemoryStorage(),
    configurable: true,
    writable: true,
  });
  useChallengeViewStore.setState({ viewMode: "card", expanded: [] });
});

describe("challenge-view store", () => {
  it("defaults to the card grid with nothing expanded", () => {
    const state = useChallengeViewStore.getState();
    expect(state.viewMode).toBe("card");
    expect(state.expanded).toEqual([]);
  });

  it("setViewMode updates state and persists to localStorage", () => {
    useChallengeViewStore.getState().setViewMode("list");
    expect(useChallengeViewStore.getState().viewMode).toBe("list");
    expect(window.localStorage.getItem("fp:challenges-view")).toBe("list");
  });

  it("toggleCategory adds then removes an id, persisting each time", () => {
    const { toggleCategory } = useChallengeViewStore.getState();
    toggleCategory("web");
    expect(useChallengeViewStore.getState().expanded).toEqual(["web"]);
    expect(
      JSON.parse(window.localStorage.getItem("fp:challenges-expanded") ?? "[]"),
    ).toEqual(["web"]);

    toggleCategory("web");
    expect(useChallengeViewStore.getState().expanded).toEqual([]);
    expect(
      JSON.parse(window.localStorage.getItem("fp:challenges-expanded") ?? "null"),
    ).toEqual([]);
  });

  it("hydrate restores a saved view mode and expanded set", () => {
    window.localStorage.setItem("fp:challenges-view", "list");
    window.localStorage.setItem("fp:challenges-expanded", JSON.stringify(["a", "b"]));
    useChallengeViewStore.getState().hydrate();
    const state = useChallengeViewStore.getState();
    expect(state.viewMode).toBe("list");
    expect(state.expanded).toEqual(["a", "b"]);
  });

  it("hydrate ignores a bogus view mode and corrupt expanded JSON", () => {
    window.localStorage.setItem("fp:challenges-view", "nonsense");
    window.localStorage.setItem("fp:challenges-expanded", "{not json");
    useChallengeViewStore.getState().hydrate();
    const state = useChallengeViewStore.getState();
    // Falls back to the SSR-safe defaults rather than throwing.
    expect(state.viewMode).toBe("card");
    expect(state.expanded).toEqual([]);
  });

  it("hydrate drops non-string entries from a tampered expanded array", () => {
    window.localStorage.setItem(
      "fp:challenges-expanded",
      JSON.stringify(["ok", 3, null, "also-ok"]),
    );
    useChallengeViewStore.getState().hydrate();
    expect(useChallengeViewStore.getState().expanded).toEqual(["ok", "also-ok"]);
  });
});
