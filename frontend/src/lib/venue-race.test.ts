import { describe, expect, it } from "vitest";

import type { TimelineSeries } from "@/lib/timeline-chart";
import type { PublicRecentSolve, PublicScoreboard } from "@/lib/types";
import {
  biggestClimber,
  biggestRankClimb,
  closestRace,
  fitCount,
  hotStreak,
  leadChanges,
  leadMargin,
  stackLabels,
  timelineEnd,
  valueAt,
} from "@/lib/venue-race";

const T0 = Date.parse("2026-08-02T10:00:00Z");
const at = (minutes: number) => new Date(T0 + minutes * 60_000).toISOString();

function series(id: string, points: [number, number][]): TimelineSeries {
  return { subject_id: id, name: id.toUpperCase(), points: points.map(([m, p]) => ({ t: at(m), points: p })) };
}

type Entry = PublicScoreboard["entries"][number];
const entry = (rank: number, name: string, points: number): Entry => ({
  rank,
  subject_id: name,
  name,
  points,
  last_solve_at: null,
  bracket: null,
});

const solve = (subject_name: string, challenge_id = "c"): PublicRecentSolve => ({
  challenge_id,
  title: challenge_id,
  subject_name,
  solved_at: at(0),
  points: 100,
  is_first_blood: false,
});

describe("valueAt", () => {
  const s = series("a", [[0, 0], [10, 100], [30, 250]]);

  it("reads the step function: the last point on or before the instant", () => {
    expect(valueAt(s, T0 + 10 * 60_000)).toBe(100);
    expect(valueAt(s, T0 + 29 * 60_000)).toBe(100);
    expect(valueAt(s, T0 + 30 * 60_000)).toBe(250);
    expect(valueAt(s, T0 + 999 * 60_000)).toBe(250);
  });

  it("is 0 before the first point", () => {
    expect(valueAt(s, T0 - 1)).toBe(0);
  });
});

describe("timelineEnd", () => {
  it("is the API's end, falling back to the latest point", () => {
    const s = series("a", [[0, 0], [40, 10]]);
    expect(timelineEnd({ end: at(60), series: [s] })).toBe(T0 + 60 * 60_000);
    expect(timelineEnd({ end: null, series: [s] })).toBe(T0 + 40 * 60_000);
    expect(timelineEnd({ end: null, series: [] })).toBe(0);
  });
});

describe("leadMargin", () => {
  it("is first over second, once someone has scored", () => {
    expect(leadMargin([entry(1, "a", 500), entry(2, "b", 350), entry(3, "c", 10)])).toEqual({
      leader: "a",
      runnerUp: "b",
      margin: 150,
    });
    expect(leadMargin([entry(1, "a", 500), entry(1, "b", 500)])).toEqual({
      leader: "a",
      runnerUp: "b",
      margin: 0,
    });
  });

  it("is nothing with one entrant or an all-zero board", () => {
    expect(leadMargin([entry(1, "a", 500)])).toBeNull();
    expect(leadMargin([entry(1, "a", 0), entry(1, "b", 0)])).toBeNull();
    expect(leadMargin([])).toBeNull();
  });
});

describe("leadChanges", () => {
  it("counts each time a different entrant goes ahead, and names the last", () => {
    const a = series("a", [[0, 0], [10, 100], [50, 400]]);
    const b = series("b", [[0, 0], [20, 200], [30, 300]]);
    // a leads at 10; b passes at 20 (1); a passes back at 50 (2).
    expect(leadChanges([a, b])).toEqual({ count: 2, last: { name: "A", at: T0 + 50 * 60_000 } });
  });

  it("doesn't count the first scorer, and a tie keeps the sitting leader", () => {
    const a = series("a", [[0, 0], [10, 100]]);
    const b = series("b", [[0, 0], [20, 100]]);
    expect(leadChanges([a, b])).toEqual({ count: 0, last: null });
    expect(leadChanges([])).toEqual({ count: 0, last: null });
  });

  it("breaks a same-instant pass by subject id so the answer is stable", () => {
    const a = series("a", [[0, 0], [10, 100]]);
    const b = series("b", [[0, 0], [20, 300]]);
    const c = series("c", [[0, 0], [20, 300]]);
    expect(leadChanges([c, b, a])).toEqual({ count: 1, last: { name: "B", at: T0 + 20 * 60_000 } });
  });
});

describe("biggestClimber", () => {
  const a = series("a", [[0, 0], [10, 100], [50, 400]]);
  const b = series("b", [[0, 0], [20, 200], [55, 550]]);

  it("is whoever gained most inside the window", () => {
    // Window 20..60: a gained 300 (100 → 400), b gained 350 (200 → 550).
    expect(biggestClimber([a, b], 40 * 60_000, T0 + 60 * 60_000)).toEqual({ name: "B", gained: 350 });
    // Window 51..60: only b moved.
    expect(biggestClimber([a, b], 9 * 60_000, T0 + 60 * 60_000)).toEqual({ name: "B", gained: 550 - 200 });
  });

  it("is nothing when no one moved in the window", () => {
    expect(biggestClimber([a, b], 60_000, T0 + 120 * 60_000)).toBeNull();
    expect(biggestClimber([], 60_000, T0)).toBeNull();
  });
});

describe("biggestRankClimb", () => {
  it("is whoever rose the most places, with competition ranking for ties", () => {
    const a = series("a", [[0, 0], [10, 300]]);
    const b = series("b", [[0, 0], [10, 200]]);
    const c = series("c", [[0, 0], [10, 100], [50, 350]]);
    const d = series("d", [[0, 0], [10, 100], [50, 200]]);
    // At 20: a=1, b=2, c=3, d=3. At 60: c=1, a=2, b=3, d=3 → c climbed 2.
    expect(biggestRankClimb([a, b, c, d], 40 * 60_000, T0 + 60 * 60_000)).toEqual({ name: "C", places: 2 });
  });

  it("is nothing when the order didn't change", () => {
    const a = series("a", [[0, 0], [10, 300], [50, 400]]);
    const b = series("b", [[0, 0], [10, 200]]);
    expect(biggestRankClimb([a, b], 40 * 60_000, T0 + 60 * 60_000)).toBeNull();
  });

  it("doesn't call breaking a tie a climb", () => {
    // a and b were level in first; b edging ahead is still first place.
    const a = series("a", [[0, 0], [10, 300]]);
    const b = series("b", [[0, 0], [10, 300], [50, 400]]);
    const c = series("c", [[0, 0], [10, 100]]);
    expect(biggestRankClimb([a, b, c], 40 * 60_000, T0 + 60 * 60_000)).toBeNull();
  });
});

describe("closestRace", () => {
  it("is the adjacent pair with the smallest gap among scorers", () => {
    const board = [entry(1, "a", 500), entry(2, "b", 300), entry(3, "c", 280), entry(4, "d", 0)];
    expect(closestRace(board)).toMatchObject({ upper: { name: "b" }, lower: { name: "c" }, gap: 20 });
  });

  it("reports a tie as a zero gap, and nothing with fewer than two scorers", () => {
    expect(closestRace([entry(1, "a", 500), entry(1, "b", 500)])).toMatchObject({ gap: 0 });
    expect(closestRace([entry(1, "a", 500), entry(2, "b", 0)])).toBeNull();
    expect(closestRace([])).toBeNull();
  });
});

describe("hotStreak", () => {
  it("is the newest-first run of one entrant, two or more long", () => {
    expect(hotStreak([solve("x"), solve("x"), solve("x"), solve("y"), solve("x")])).toEqual({
      name: "x",
      count: 3,
    });
    expect(hotStreak([solve("x"), solve("y"), solve("y")])).toBeNull();
    expect(hotStreak([])).toBeNull();
  });
});

describe("fitCount", () => {
  it("fits whole rows including the gaps between them, capped at max", () => {
    // 3 rows of 40 + 2 gaps of 10 = 140 ≤ 150; a 4th would need 190.
    expect(fitCount(150, 40, 10, 10)).toBe(3);
    expect(fitCount(140, 40, 10, 10)).toBe(3);
    expect(fitCount(150, 40, 10, 2)).toBe(2);
    expect(fitCount(39, 40, 10, 10)).toBe(0);
  });

  it("drops nothing on an unmeasured row, and nothing at all for max 0", () => {
    expect(fitCount(150, 0, 10, 7)).toBe(7);
    expect(fitCount(150, 40, 10, 0)).toBe(0);
  });
});

describe("stackLabels", () => {
  it("leaves spaced labels alone and pushes crowded ones apart, in line order", () => {
    const laid = stackLabels(
      [
        { id: "a", y: 10 },
        { id: "b", y: 12 },
        { id: "c", y: 100 },
      ],
      20,
      0,
      200,
    );
    expect([...laid.entries()]).toEqual([
      ["a", 10],
      ["b", 30],
      ["c", 100],
    ]);
  });

  it("walks the stack back up when it would run off the bottom", () => {
    const laid = stackLabels(
      [
        { id: "a", y: 190 },
        { id: "b", y: 195 },
      ],
      20,
      0,
      200,
    );
    expect(laid.get("b")).toBe(200);
    expect(laid.get("a")).toBe(180);
  });

  it("clamps at the top", () => {
    expect(stackLabels([{ id: "a", y: -5 }], 20, 0, 200).get("a")).toBe(0);
  });
});

