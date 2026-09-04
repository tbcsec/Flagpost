import { describe, expect, it } from "vitest";

import { axisColor, buildRadar, radarMax } from "./skills-radar";

describe("radarMax", () => {
  it("is the strongest axis, floored at 1", () => {
    expect(radarMax([5, 3, 1])).toBe(5);
    expect(radarMax([])).toBe(1);
    expect(radarMax([0, 0])).toBe(1);
  });
});

describe("axisColor", () => {
  it("wraps the ten chart tokens and never emits a raw hex", () => {
    expect(axisColor(0)).toBe("hsl(var(--chart-1))");
    expect(axisColor(9)).toBe("hsl(var(--chart-10))");
    expect(axisColor(10)).toBe("hsl(var(--chart-1))"); // wraps
    expect(axisColor(3)).not.toMatch(/#/);
  });
});

describe("buildRadar", () => {
  it("lays axes evenly, first one at the top", () => {
    const g = buildRadar(
      [
        { skill: "web", score: 4 },
        { skill: "pwn", score: 2 },
        { skill: "crypto", score: 1 },
      ],
      { size: 320 },
    );
    expect(g.axes).toHaveLength(3);
    expect(g.maxScore).toBe(4);
    // First axis points straight up (angle -PI/2): x at centre, y above it.
    const [first] = g.axes;
    expect(first.angle).toBeCloseTo(-Math.PI / 2);
    expect(first.axisX).toBeCloseTo(g.cx);
    expect(first.axisY).toBeLessThan(g.cy);
    // The strongest axis reaches the outer ring; a weaker one sits inside it.
    expect(Math.hypot(first.pointX - g.cx, first.pointY - g.cy)).toBeCloseTo(g.radius);
    const crypto = g.axes[2];
    expect(Math.hypot(crypto.pointX - g.cx, crypto.pointY - g.cy)).toBeLessThan(g.radius);
  });

  it("emits a data polygon and concentric grid rings", () => {
    const g = buildRadar([
      { skill: "a", score: 1 },
      { skill: "b", score: 1 },
      { skill: "c", score: 1 },
    ]);
    // One "x,y" pair per axis in the web polygon.
    expect(g.polygon.trim().split(/\s+/)).toHaveLength(3);
    expect(g.rings.length).toBeGreaterThanOrEqual(3);
    // Every ring is a closed set of points for each axis.
    for (const ring of g.rings) {
      expect(ring.trim().split(/\s+/)).toHaveLength(3);
    }
  });

  it("does not divide by zero for an all-zero web", () => {
    const g = buildRadar([
      { skill: "a", score: 0 },
      { skill: "b", score: 0 },
    ]);
    expect(g.maxScore).toBe(1);
    for (const axis of g.axes) {
      expect(Number.isFinite(axis.pointX)).toBe(true);
      expect(Number.isFinite(axis.pointY)).toBe(true);
    }
  });
});
