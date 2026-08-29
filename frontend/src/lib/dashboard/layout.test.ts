import { describe, expect, it } from "vitest";

import {
  addEntry,
  applyGridItems,
  catalogFor,
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
  a: { id: "a", labelKey: "stats", audiences: ["manager"], minSize: { w: 4, h: 1 }, defaultSize: { w: 12, h: 2 }, Component: Noop },
  b: { id: "b", labelKey: "standing", audiences: ["participant"], minSize: { w: 4, h: 3 }, defaultSize: { w: 6, h: 5 }, Component: Noop },
  c: { id: "c", labelKey: "activity", audiences: ["manager", "participant"], minSize: { w: 4, h: 3 }, defaultSize: { w: 6, h: 5 }, Component: Noop },
};

const DEFAULT: LayoutEntry[] = [
  { widgetId: "a", x: 0, y: 0, w: 12, h: 2 },
  { widgetId: "b", x: 0, y: 2, w: 6, h: 5 },
];

describe("clampEntry", () => {
  it("clamps width to the widget minimum and the grid, and keeps it on-grid", () => {
    const e = clampEntry(REG.a, { widgetId: "a", x: 20, y: -3, w: 1, h: 0 });
    expect(e).toEqual({ widgetId: "a", x: 8, y: 0, w: 4, h: 1 });
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

  it("renders exactly the saved (added) set, clamping — no `hidden` carried", () => {
    const saved: DashboardLayoutEntry[] = [
      { widget_id: "b", x: 6, y: 0, w: 6, h: 4 },
      { widget_id: "a", x: 0, y: 4, w: 8, h: 1 },
    ];
    expect(mergeLayout(saved, DEFAULT, REG)).toEqual([
      { widgetId: "b", x: 6, y: 0, w: 6, h: 4 },
      { widgetId: "a", x: 0, y: 4, w: 8, h: 1 },
    ]);
  });

  it("does NOT re-append default widgets missing from a saved layout (#330)", () => {
    // Under the catalog model a removed section stays gone; only the Add-section
    // modal brings it back. So a save with just `a` renders just `a` — `b` (a
    // default) is not auto-placed.
    const saved: DashboardLayoutEntry[] = [{ widget_id: "a", x: 0, y: 0, w: 12, h: 2 }];
    expect(mergeLayout(saved, DEFAULT, REG).map((e) => e.widgetId)).toEqual(["a"]);
  });

  it("drops a legacy `hidden: true` entry (old hide == not added, #330)", () => {
    const saved: DashboardLayoutEntry[] = [
      { widget_id: "a", x: 0, y: 0, w: 12, h: 2, hidden: false },
      { widget_id: "b", x: 0, y: 2, w: 6, h: 5, hidden: true },
    ];
    expect(mergeLayout(saved, DEFAULT, REG).map((e) => e.widgetId)).toEqual(["a"]);
  });

  it("resets a pre-#21 {cols,rows} layout to the default (backward compat)", () => {
    // Old ordered-flow saves have no x/y/w/h — they can't map to 2D, so each is
    // treated as unrecognized and the default layout applies instead.
    const stale = [
      { widget_id: "a", cols: 4, rows: 1 },
      { widget_id: "b", cols: 2, rows: 2 },
    ] as unknown as DashboardLayoutEntry[];
    // No valid 2D entries survive → renders nothing (an empty dashboard), which
    // the customize UI then lets the user rebuild from the catalog.
    expect(mergeLayout(stale, DEFAULT, REG)).toEqual([]);
  });

  it("drops entries for widgets no longer in the registry", () => {
    const saved: DashboardLayoutEntry[] = [
      { widget_id: "ghost", x: 0, y: 0, w: 6, h: 4 },
      { widget_id: "a", x: 0, y: 0, w: 12, h: 2 },
    ];
    expect(mergeLayout(saved, DEFAULT, REG).map((e) => e.widgetId)).toEqual(["a"]);
  });

  it("clamps a saved size below the widget minimum back up to the minimum", () => {
    const saved: DashboardLayoutEntry[] = [{ widget_id: "b", x: 0, y: 0, w: 1, h: 1 }];
    expect(mergeLayout(saved, DEFAULT, REG)[0]).toMatchObject({ widgetId: "b", w: 4, h: 3 });
  });
});

describe("toSaved", () => {
  it("serializes to the 2D wire shape without `hidden` (#330)", () => {
    const entries: LayoutEntry[] = [
      { widgetId: "a", x: 0, y: 0, w: 12, h: 2 },
      { widgetId: "b", x: 0, y: 2, w: 6, h: 5 },
    ];
    expect(toSaved(entries)).toEqual([
      { widget_id: "a", x: 0, y: 0, w: 12, h: 2 },
      { widget_id: "b", x: 0, y: 2, w: 6, h: 5 },
    ]);
  });
});

describe("catalogFor", () => {
  it("offers the audience's eligible sections that aren't already present", () => {
    // manager-eligible = a, c (b is participant-only). `a` is present → only `c`.
    const present: LayoutEntry[] = [{ widgetId: "a", x: 0, y: 0, w: 12, h: 2 }];
    expect(catalogFor("manager", present, REG).map((w) => w.id)).toEqual(["c"]);
  });

  it("excludes sections not tagged for the audience", () => {
    // participant-eligible = b, c; none present → both, in registry order.
    expect(catalogFor("participant", [], REG).map((w) => w.id)).toEqual(["b", "c"]);
  });

  it("returns empty when every eligible section is already on the dashboard", () => {
    const present: LayoutEntry[] = [
      { widgetId: "a", x: 0, y: 0, w: 12, h: 2 },
      { widgetId: "c", x: 0, y: 2, w: 6, h: 5 },
    ];
    expect(catalogFor("manager", present, REG)).toEqual([]);
  });
});

describe("addEntry", () => {
  it("places a new section at the bottom at its default size, clamped", () => {
    const entries: LayoutEntry[] = [{ widgetId: "a", x: 0, y: 0, w: 12, h: 2 }];
    const next = addEntry(entries, REG.c);
    expect(next).toHaveLength(2);
    expect(next[1]).toEqual({ widgetId: "c", x: 0, y: 2, w: 6, h: 5 }); // below `a` (y=0+h=2)
  });

  it("places at the top of an empty dashboard", () => {
    expect(addEntry([], REG.b)[0]).toMatchObject({ widgetId: "b", x: 0, y: 0, w: 6, h: 5 });
  });
});

describe("toGridItems / applyGridItems", () => {
  it("projects entries into RGL items carrying the registry minimums", () => {
    expect(toGridItems(DEFAULT, REG)).toEqual([
      { i: "a", x: 0, y: 0, w: 12, h: 2, minW: 4, minH: 1 },
      { i: "b", x: 0, y: 2, w: 6, h: 5, minW: 4, minH: 3 },
    ]);
  });

  it("folds RGL positions back in, preserving id and order", () => {
    const entries: LayoutEntry[] = [
      { widgetId: "a", x: 0, y: 0, w: 12, h: 2 },
      { widgetId: "b", x: 0, y: 2, w: 6, h: 5 },
    ];
    // RGL may return items in a different order.
    const items = [
      { i: "b", x: 6, y: 0, w: 6, h: 4 },
      { i: "a", x: 0, y: 4, w: 8, h: 3 },
    ];
    expect(applyGridItems(entries, items)).toEqual([
      { widgetId: "a", x: 0, y: 4, w: 8, h: 3 },
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
