import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { QueryKey } from "@tanstack/react-query";

import {
  ACTIVITY_THROTTLE_MS,
  applyChallengeDelta,
  createThrottledInvalidator,
  keysForActivity,
} from "@/lib/live";

const CID = "comp-1";

describe("keysForActivity", () => {
  it("maps a solve to the standings surfaces but NOT the challenge list", () => {
    // The challenge list is patched in place from the solve delta (#188), so a
    // solve must no longer trigger a full ["challenges"] refetch across watchers.
    const keys = keysForActivity("challenge.solved", CID);
    expect(keys).not.toContainEqual(["challenges", CID]);
    expect(keys).toContainEqual(["dashboard", CID, "stats"]);
    expect(keys).toContainEqual(["dashboard", CID, "recent-solves"]);
    expect(keys).toContainEqual(["dashboard", CID, "me"]);
    expect(keys).toContainEqual(["analytics", CID]);
    expect(keys).toContainEqual(["participants", CID]);
  });

  it("never touches the dashboard layout key", () => {
    // A live ping must not clobber an in-progress layout edit.
    for (const event of [
      "challenge.solved",
      "challenge.attempted",
      "challenge.published",
    ]) {
      for (const key of keysForActivity(event, CID)) {
        expect(key).not.toContainEqual("layout");
      }
    }
  });

  it("keeps attempts off the challenge list (heaviest refetch, most frequent event)", () => {
    const keys = keysForActivity("challenge.attempted", CID);
    expect(keys).not.toContainEqual(["challenges", CID]);
    expect(keys).toContainEqual(["dashboard", CID, "challenge-health"]);
    expect(keys).toContainEqual(["analytics", CID]);
  });

  it("maps roster and module events", () => {
    expect(keysForActivity("team.created", CID)).toContainEqual(["teams", CID]);
    expect(keysForActivity("competition.member_joined", CID)).toContainEqual([
      "participants",
      CID,
    ]);
    expect(keysForActivity("module.enabled", CID)).toEqual([["modules", CID]]);
    expect(keysForActivity("competition.updated", CID)).toEqual([["competitions"]]);
  });

  it("maps instance lifecycle events to the instance query prefix", () => {
    // The subject's open instance panel refetches as it moves through the
    // lifecycle; the ["instance", cid] prefix covers whichever dialog is open.
    for (const event of [
      "challenge.instance_requested",
      "challenge.instance_started",
      "challenge.instance_extended",
      "challenge.instance_expired",
      "challenge.instance_destroyed",
      "challenge.instance_provision_failed",
    ]) {
      expect(keysForActivity(event, CID)).toEqual([["instance", CID]]);
    }
  });

  it("returns nothing for unmapped events (frontend allowlist)", () => {
    expect(keysForActivity("user.banned", CID)).toEqual([]);
    expect(keysForActivity("something.new", CID)).toEqual([]);
  });
});

describe("applyChallengeDelta (#188)", () => {
  const list = [
    { id: "a", solve_count: 1, value: 500 },
    { id: "b", solve_count: 3, value: 420 },
  ];

  it("patches solve_count and value on the matching challenge only", () => {
    const next = applyChallengeDelta(list, "b", 4, 380);
    expect(next).not.toBe(list); // new reference → triggers a render
    expect(next).toEqual([
      { id: "a", solve_count: 1, value: 500 },
      { id: "b", solve_count: 4, value: 380 },
    ]);
    expect(next![0]).toBe(list[0]); // untouched row keeps its reference
  });

  it("leaves value untouched when the delta omits it (static scoring)", () => {
    const next = applyChallengeDelta(list, "a", 2, undefined);
    expect(next![0]).toEqual({ id: "a", solve_count: 2, value: 500 });
  });

  it("returns the same reference when nothing matches (no needless render)", () => {
    expect(applyChallengeDelta(list, "missing", 9, 9)).toBe(list);
  });

  it("is a no-op on an unpopulated cache", () => {
    expect(applyChallengeDelta(undefined, "a", 2, 1)).toBeUndefined();
  });
});

describe("createThrottledInvalidator", () => {
  let fired: QueryKey[];
  let invalidator: ReturnType<typeof createThrottledInvalidator>;

  beforeEach(() => {
    vi.useFakeTimers();
    fired = [];
    invalidator = createThrottledInvalidator((key) => fired.push(key));
  });

  afterEach(() => {
    invalidator.dispose();
    vi.useRealTimers();
  });

  it("fires immediately on the first hit (leading edge)", () => {
    invalidator.push([["challenges", CID]]);
    expect(fired).toEqual([["challenges", CID]]);
  });

  it("coalesces a burst into one trailing fire", () => {
    invalidator.push([["challenges", CID]]);
    invalidator.push([["challenges", CID]]);
    invalidator.push([["challenges", CID]]);
    expect(fired).toHaveLength(1);

    vi.advanceTimersByTime(ACTIVITY_THROTTLE_MS);
    expect(fired).toHaveLength(2); // the burst's trailing fire — never lost
  });

  it("stays quiet after the window when nothing arrived during it", () => {
    invalidator.push([["challenges", CID]]);
    vi.advanceTimersByTime(ACTIVITY_THROTTLE_MS * 3);
    expect(fired).toHaveLength(1);
  });

  it("throttles keys independently", () => {
    invalidator.push([["challenges", CID]]);
    invalidator.push([["participants", CID]]);
    expect(fired).toEqual([
      ["challenges", CID],
      ["participants", CID],
    ]);
  });

  it("fires at most once per window under a steady stream", () => {
    // Six events over three windows → leading + one trailing per window edge.
    for (let i = 0; i < 6; i++) {
      invalidator.push([["challenges", CID]]);
      vi.advanceTimersByTime(ACTIVITY_THROTTLE_MS / 2);
    }
    vi.advanceTimersByTime(ACTIVITY_THROTTLE_MS);
    expect(fired.length).toBe(4);
  });

  it("dispose cancels pending trailing fires", () => {
    invalidator.push([["challenges", CID]]);
    invalidator.push([["challenges", CID]]);
    invalidator.dispose();
    vi.advanceTimersByTime(ACTIVITY_THROTTLE_MS * 2);
    expect(fired).toHaveLength(1);
  });
});

describe("createThrottledInvalidator jitter (#175)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("delays the refetch by random()*jitterMs instead of firing synchronously", () => {
    const fired: QueryKey[] = [];
    const inv = createThrottledInvalidator((k) => fired.push(k), ACTIVITY_THROTTLE_MS, {
      jitterMs: 500,
      random: () => 0.5, // deterministic: fire at 250ms
    });

    inv.push([["challenges", CID]]);
    expect(fired).toHaveLength(0); // not synchronous — jittered
    vi.advanceTimersByTime(249);
    expect(fired).toHaveLength(0);
    vi.advanceTimersByTime(1);
    expect(fired).toEqual([["challenges", CID]]); // fired at 250ms
    inv.dispose();
  });

  it("dispose clears a pending jittered refetch", () => {
    const fired: QueryKey[] = [];
    const inv = createThrottledInvalidator((k) => fired.push(k), ACTIVITY_THROTTLE_MS, {
      jitterMs: 500,
      random: () => 0.9,
    });
    inv.push([["challenges", CID]]);
    inv.dispose();
    vi.advanceTimersByTime(500);
    expect(fired).toHaveLength(0);
  });
});
