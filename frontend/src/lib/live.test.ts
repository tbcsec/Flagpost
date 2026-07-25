import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { QueryKey } from "@tanstack/react-query";

import {
  ACTIVITY_THROTTLE_MS,
  createThrottledInvalidator,
  keysForActivity,
} from "@/lib/live";

const CID = "comp-1";

describe("keysForActivity", () => {
  it("maps a solve to the play surfaces", () => {
    const keys = keysForActivity("challenge.solved", CID);
    expect(keys).toContainEqual(["challenges", CID]);
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

  it("returns nothing for unmapped events (frontend allowlist)", () => {
    expect(keysForActivity("user.banned", CID)).toEqual([]);
    expect(keysForActivity("something.new", CID)).toEqual([]);
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
