import { describe, expect, it } from "vitest";

import {
  DEFAULT_BOX,
  buildScales,
  niceMax,
  seriesColor,
  seriesPolyline,
  xTicks,
  yTicks,
  type TimelineSeries,
} from "@/lib/timeline-chart";

const START = "2026-01-01T00:00:00Z";
const END = "2026-01-01T04:00:00Z";

function series(points: [string, number][]): TimelineSeries {
  return {
    subject_id: "s1",
    name: "Ada",
    points: points.map(([t, p]) => ({ t, points: p })),
  };
}

describe("niceMax", () => {
  it("rounds up to a readable axis top", () => {
    expect(niceMax(1)).toBe(1);
    expect(niceMax(140)).toBe(200);
    expect(niceMax(350)).toBe(500);
    expect(niceMax(940)).toBe(1000);
  });

  it("never returns zero, so the y scale can't divide by it", () => {
    expect(niceMax(0)).toBe(1);
    expect(niceMax(-5)).toBe(1);
    expect(niceMax(Number.NaN)).toBe(1);
  });
});

describe("buildScales", () => {
  const one = series([
    [START, 0],
    ["2026-01-01T02:00:00Z", 300],
  ]);

  it("maps the window onto the drawable box", () => {
    const scales = buildScales([one], START, END);
    expect(scales.x(scales.t0)).toBe(DEFAULT_BOX.padding.left);
    expect(scales.x(scales.t1)).toBe(DEFAULT_BOX.width - DEFAULT_BOX.padding.right);
    // y is inverted: zero sits on the baseline, the max at the top.
    expect(scales.y(0)).toBe(DEFAULT_BOX.height - DEFAULT_BOX.padding.bottom);
    expect(scales.y(scales.yMax)).toBe(DEFAULT_BOX.padding.top);
  });

  it("falls back to the data range when the window is missing", () => {
    const scales = buildScales([one], null, null);
    expect(scales.t0).toBe(new Date(START).getTime());
    expect(scales.t1).toBe(new Date("2026-01-01T02:00:00Z").getTime());
  });

  it("survives a zero-width window (everything at one instant)", () => {
    const scales = buildScales([series([[START, 10]])], START, START);
    expect(scales.t1).toBeGreaterThan(scales.t0);
    expect(Number.isFinite(scales.x(scales.t0))).toBe(true);
  });

  it("survives an all-zero board", () => {
    const scales = buildScales([series([[START, 0]])], START, END);
    expect(scales.yMax).toBe(1);
    expect(Number.isFinite(scales.y(0))).toBe(true);
  });

  it("handles empty series without producing NaN", () => {
    const scales = buildScales([], null, null);
    expect(Number.isFinite(scales.x(scales.t0))).toBe(true);
    expect(Number.isFinite(scales.y(0))).toBe(true);
  });
});

describe("seriesPolyline", () => {
  it("steps: holds the old value to the new time, then jumps", () => {
    const scales = buildScales([], START, END);
    const line = seriesPolyline(
      series([
        [START, 0],
        ["2026-01-01T02:00:00Z", 100],
      ]),
      scales,
    );
    const coords = line.split(" ").map((pair) => pair.split(",").map(Number));
    // Two coords per point (hold + jump), plus the extension to the window end.
    expect(coords).toHaveLength(5);
    const [holdX, holdY] = coords[2];
    const [jumpX, jumpY] = coords[3];
    expect(holdX).toBe(jumpX); // vertical jump at the solve instant
    expect(jumpY).toBeLessThan(holdY); // more points = higher on screen
    // The final coord carries the series to the right edge.
    expect(coords[4][0]).toBeCloseTo(scales.x(scales.t1));
    expect(coords[4][1]).toBeCloseTo(jumpY);
  });

  it("returns an empty string for an empty series", () => {
    expect(seriesPolyline(series([]), buildScales([], START, END))).toBe("");
  });

  it("clamps points outside the window rather than drawing off-canvas", () => {
    const scales = buildScales([], "2026-01-01T01:00:00Z", END);
    const line = seriesPolyline(series([[START, 50]]), scales);
    const xs = line.split(" ").map((pair) => Number(pair.split(",")[0]));
    expect(Math.min(...xs)).toBeGreaterThanOrEqual(scales.x(scales.t0));
  });
});

describe("axis ticks", () => {
  it("yTicks spans zero to the axis top", () => {
    const ticks = yTicks(buildScales([series([[START, 300]])], START, END), 4);
    expect(ticks).toHaveLength(5);
    expect(ticks[0].value).toBe(0);
    expect(ticks[4].value).toBe(500); // niceMax(300)
  });

  it("xTicks spans the window", () => {
    const scales = buildScales([], START, END);
    const ticks = xTicks(scales, 4);
    expect(ticks[0].at).toBe(scales.t0);
    expect(ticks[4].at).toBe(scales.t1);
  });
});

describe("seriesColor", () => {
  it("uses design tokens and wraps past ten", () => {
    expect(seriesColor(0)).toBe("hsl(var(--chart-1))");
    expect(seriesColor(9)).toBe("hsl(var(--chart-10))");
    expect(seriesColor(10)).toBe("hsl(var(--chart-1))");
  });
});
