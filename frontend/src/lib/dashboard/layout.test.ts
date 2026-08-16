import { describe, expect, it } from "vitest";

import {
  applyGridItems,
  clampEntry,
  mergeLayout,
  nudgeEntry,
  resizeEntry,
  toGridItems,
  toSaved,
} from "@/lib/dashboard/layout";
import type { LayoutEntry, WidgetDef } from "@/lib/dashboard/registry";
import type { DashboardLayoutEntry } from "@/lib/types";

// A minimal fixture registry so these stay pure (no component imports needed).
const Noop = (() => null) as unknown as WidgetDef["Component"];
const REG: Record<string, WidgetDef> = {
  a: { id: "a", labelKey: "stats", minSize: { w: 4, h: 1 }, defaultSize: { w: 12, h: 2 }, Component: Noop },
  b: { id: "b", labelKey: "standing", minSize: { w: 4, h: 3 }, defaultSize: { w: 6, h: 5 }, Component: Noop },
};

const DEFAULT: LayoutEntry[] = [
  { widgetId: "a", x: 0, y: 0, w: 12, h: 2 },
  { widgetId: "b", x: 0, y: 2, w: 6, h: 5 },
];

describe("clampEntry", () => {
  it("clamps width to the widget minimum and the grid, and keeps it on-grid", () => {
    const e = clampEntry(REG.a, { widgetId: "a", x: 20, y: -3, w: 1, h: 0 });
    expect(e).toEqual({ widgetId: "a", x: 8, y: 0, w: 4, h: 1, hidden: undefined });
  });

  it("caps width at the 12-column grid", () => {
    const e = clampEntry(REG.b, { widgetId: "b", x: 0, y: 0, w: 99, h: 4 });
    expect(e.w).toBe(12);
    expect(e.x).toBe(0);
  });
});

describe("mergeLayout", () => {
  it("returns the default (cloned) when nothing is saved", () => {
    const merged = mergeLayout(null, DEFAULT, REG);
    expect(merged).toEqual(DEFAULT);
    expect(merged[0]).not.toBe(DEFAULT[0]); // cloned, not aliased
  });

  it("round-trips a saved 2D layout, clamping and preserving hidden state", () => {
    const saved: DashboardLayoutEntry[] = [
      { widget_id: "b", x: 6, y: 0, w: 6, h: 4, hidden: false },
      { widget_id: "a", x: 0, y: 4, w: 8, h: 1, hidden: true },
    ];
    expect(mergeLayout(saved, DEFAULT, REG)).toEqual([
      { widgetId: "b", x: 6, y: 0, w: 6, h: 4, hidden: false },
      { widgetId: "a", x: 0, y: 4, w: 8, h: 1, hidden: true },
    ]);
  });

  it("resets a pre-#21 {cols,rows} layout to the default (backward compat)", () => {
    // Old ordered-flow saves have no x/y/w/h — they can't map to 2D, so each is
    // treated as unrecognized and the default layout applies instead.
    const stale = [
      { widget_id: "a", cols: 4, rows: 1, hidden: false },
      { widget_id: "b", cols: 2, rows: 2, hidden: false },
    ] as unknown as DashboardLayoutEntry[];
    expect(mergeLayout(stale, DEFAULT, REG)).toEqual(DEFAULT);
  });

  it("drops entries for widgets no longer in the registry, appending missing defaults", () => {
    const saved: DashboardLayoutEntry[] = [
      { widget_id: "ghost", x: 0, y: 0, w: 6, h: 4, hidden: false },
      { widget_id: "a", x: 0, y: 0, w: 12, h: 2, hidden: false },
    ];
    const merged = mergeLayout(saved, DEFAULT, REG);
    expect(merged.map((e) => e.widgetId)).toEqual(["a", "b"]); // ghost gone, b appended
  });

  it("clamps a saved size below the widget minimum back up to the minimum", () => {
    const saved: DashboardLayoutEntry[] = [
      { widget_id: "b", x: 0, y: 0, w: 1, h: 1, hidden: false },
    ];
    const merged = mergeLayout(saved, DEFAULT, REG);
    expect(merged[0]).toMatchObject({ widgetId: "b", w: 4, h: 3 }); // min {4,3}
  });
});

describe("toSaved", () => {
  it("serializes to the 2D wire shape", () => {
    const entries: LayoutEntry[] = [
      { widgetId: "a", x: 0, y: 0, w: 12, h: 2, hidden: true },
      { widgetId: "b", x: 0, y: 2, w: 6, h: 5 },
    ];
    expect(toSaved(entries)).toEqual([
      { widget_id: "a", x: 0, y: 0, w: 12, h: 2, hidden: true },
      { widget_id: "b", x: 0, y: 2, w: 6, h: 5, hidden: false },
    ]);
  });
});

describe("toGridItems / applyGridItems", () => {
  it("projects entries into RGL items carrying the registry minimums", () => {
    expect(toGridItems(DEFAULT, REG)).toEqual([
      { i: "a", x: 0, y: 0, w: 12, h: 2, minW: 4, minH: 1 },
      { i: "b", x: 0, y: 2, w: 6, h: 5, minW: 4, minH: 3 },
    ]);
  });

  it("folds RGL positions back in, preserving id, order and hidden", () => {
    const entries: LayoutEntry[] = [
      { widgetId: "a", x: 0, y: 0, w: 12, h: 2, hidden: true },
      { widgetId: "b", x: 0, y: 2, w: 6, h: 5 },
    ];
    // RGL may return items in a different order.
    const items = [
      { i: "b", x: 6, y: 0, w: 6, h: 4 },
      { i: "a", x: 0, y: 4, w: 8, h: 3 },
    ];
    expect(applyGridItems(entries, items)).toEqual([
      { widgetId: "a", x: 0, y: 4, w: 8, h: 3, hidden: true },
      { widgetId: "b", x: 6, y: 0, w: 6, h: 4 },
    ]);
  });
});

describe("keyboard fallbacks", () => {
  it("nudge moves by whole cells, clamped on-grid", () => {
    const e: LayoutEntry = { widgetId: "b", x: 6, y: 2, w: 6, h: 5 };
    expect(nudgeEntry(REG.b, e, 1, -1)).toMatchObject({ x: 6, y: 1 }); // x can't pass the edge
    expect(nudgeEntry(REG.b, e, -1, 1)).toMatchObject({ x: 5, y: 3 });
  });

  it("resize grows/shrinks by whole cells, clamped to min and grid", () => {
    const e: LayoutEntry = { widgetId: "b", x: 6, y: 2, w: 6, h: 5 };
    expect(resizeEntry(REG.b, e, 100, -100)).toMatchObject({ w: 12, h: 3, x: 0 });
    expect(resizeEntry(REG.b, e, -1, -1)).toMatchObject({ w: 5, h: 4 });
  });
});
