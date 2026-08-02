import { describe, expect, it } from "vitest";

import type { PublicRecentSolve } from "@/lib/types";
import {
  DEFAULT_ROTATE_SECONDS,
  nextIndex,
  parseRotateSeconds,
  pickNewFirstBloods,
} from "@/lib/venue";

function solve(partial: Partial<PublicRecentSolve> & { challenge_id: string }): PublicRecentSolve {
  return {
    title: partial.challenge_id,
    subject_name: "team",
    solved_at: "2026-08-02T12:00:00Z",
    points: 100,
    is_first_blood: false,
    ...partial,
  };
}

describe("parseRotateSeconds", () => {
  it("falls back to the default for missing/garbage values", () => {
    expect(parseRotateSeconds(null)).toBe(DEFAULT_ROTATE_SECONDS);
    expect(parseRotateSeconds("")).toBe(DEFAULT_ROTATE_SECONDS);
    expect(parseRotateSeconds("abc")).toBe(DEFAULT_ROTATE_SECONDS);
  });

  it("parses a valid value and clamps out-of-range ones", () => {
    expect(parseRotateSeconds("20")).toBe(20);
    expect(parseRotateSeconds("2")).toBe(5); // clamped up to the min
    expect(parseRotateSeconds("9999")).toBe(120); // clamped down to the max
    expect(parseRotateSeconds("30.9")).toBe(30); // parseInt, not float
  });
});

describe("nextIndex", () => {
  it("advances and wraps", () => {
    expect(nextIndex(0, 3)).toBe(1);
    expect(nextIndex(2, 3)).toBe(0);
  });
  it("guards an empty slide set", () => {
    expect(nextIndex(0, 0)).toBe(0);
  });
});

describe("pickNewFirstBloods", () => {
  it("returns only unseen first bloods, oldest-first", () => {
    // Feed is newest-first: b (newest) then a (older), both fresh first bloods.
    const feed = [
      solve({ challenge_id: "b", is_first_blood: true, solved_at: "2026-08-02T12:05:00Z" }),
      solve({ challenge_id: "a", is_first_blood: true, solved_at: "2026-08-02T12:01:00Z" }),
      solve({ challenge_id: "c", is_first_blood: false }),
    ];
    const fresh = pickNewFirstBloods(feed, new Set());
    // Chronological: a happened before b, so it splashes first.
    expect(fresh.map((s) => s.challenge_id)).toEqual(["a", "b"]);
  });

  it("excludes already-seen first bloods and plain solves", () => {
    const feed = [
      solve({ challenge_id: "a", is_first_blood: true }),
      solve({ challenge_id: "b", is_first_blood: true }),
      solve({ challenge_id: "c", is_first_blood: false }),
    ];
    const fresh = pickNewFirstBloods(feed, new Set(["a"]));
    expect(fresh.map((s) => s.challenge_id)).toEqual(["b"]);
  });

  it("does not mutate the seen set", () => {
    const seen = new Set<string>();
    pickNewFirstBloods([solve({ challenge_id: "a", is_first_blood: true })], seen);
    expect(seen.size).toBe(0);
  });
});
