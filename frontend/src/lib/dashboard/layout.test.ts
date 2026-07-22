import { describe, expect, it } from "vitest";

import { cycleSize, mergeLayout, moveEntry, toSaved } from "@/lib/dashboard/layout";
import type { LayoutEntry, WidgetDef } from "@/lib/dashboard/registry";
import type { DashboardLayoutEntry } from "@/lib/types";

// A minimal fixture registry so these stay pure (no component imports needed).
const Noop = (() => null) as unknown as WidgetDef["Component"];
const REG: Record<string, WidgetDef> = {
  a: {
    id: "a",
    label: "A",
    sizes: [{ cols: 4, rows: 1 }, { cols: 2, rows: 1 }],
    defaultSize: { cols: 4, rows: 1 },
    Component: Noop,
  },
  b: {
    id: "b",
    label: "B",
    sizes: [{ cols: 2, rows: 2 }, { cols: 4, rows: 2 }],
    defaultSize: { cols: 2, rows: 2 },
    Component: Noop,
  },
};

const DEFAULT: LayoutEntry[] = [
  { widgetId: "a", size: { cols: 4, rows: 1 } },
  { widgetId: "b", size: { cols: 2, rows: 2 } },
];

describe("cycleSize", () => {
  it("steps to the next legitimate size and wraps", () => {
    expect(cycleSize(REG.a, { cols: 4, rows: 1 })).toEqual({ cols: 2, rows: 1 });
    expect(cycleSize(REG.a, { cols: 2, rows: 1 })).toEqual({ cols: 4, rows: 1 });
  });

  it("returns the first size when the current isn't recognized", () => {
    expect(cycleSize(REG.a, { cols: 3, rows: 3 })).toEqual({ cols: 4, rows: 1 });
  });
});

describe("mergeLayout", () => {
  it("returns the default (cloned) when nothing is saved", () => {
    const merged = mergeLayout(null, DEFAULT, REG);
    expect(merged).toEqual(DEFAULT);
    expect(merged[0].size).not.toBe(DEFAULT[0].size); // deep-cloned, not aliased
  });

  it("round-trips a saved layout, preserving order and hidden state", () => {
    const saved: DashboardLayoutEntry[] = [
      { widget_id: "b", cols: 4, rows: 2, hidden: false },
      { widget_id: "a", cols: 2, rows: 1, hidden: true },
    ];
    expect(mergeLayout(saved, DEFAULT, REG)).toEqual([
      { widgetId: "b", size: { cols: 4, rows: 2 }, hidden: false },
      { widgetId: "a", size: { cols: 2, rows: 1 }, hidden: true },
    ]);
  });

  it("drops entries for widgets no longer in the registry", () => {
    const saved: DashboardLayoutEntry[] = [
      { widget_id: "ghost", cols: 4, rows: 1, hidden: false },
      { widget_id: "a", cols: 4, rows: 1, hidden: false },
    ];
    const merged = mergeLayout(saved, DEFAULT, REG);
    expect(merged.map((e) => e.widgetId)).toEqual(["a", "b"]); // ghost gone, b appended
  });

  it("snaps a stale saved size back into the widget's legitimate set", () => {
    const saved: DashboardLayoutEntry[] = [
      { widget_id: "a", cols: 3, rows: 9, hidden: false },
    ];
    const merged = mergeLayout(saved, DEFAULT, REG);
    expect(merged[0].size).toEqual({ cols: 4, rows: 1 }); // fell back to default
  });

  it("appends default widgets missing from the save so new widgets surface", () => {
    const saved: DashboardLayoutEntry[] = [
      { widget_id: "a", cols: 4, rows: 1, hidden: false },
    ];
    const merged = mergeLayout(saved, DEFAULT, REG);
    expect(merged.map((e) => e.widgetId)).toEqual(["a", "b"]);
  });
});

describe("toSaved", () => {
  it("serializes to the wire shape", () => {
    const entries: LayoutEntry[] = [
      { widgetId: "a", size: { cols: 2, rows: 1 }, hidden: true },
      { widgetId: "b", size: { cols: 2, rows: 2 } },
    ];
    expect(toSaved(entries)).toEqual([
      { widget_id: "a", cols: 2, rows: 1, hidden: true },
      { widget_id: "b", cols: 2, rows: 2, hidden: false },
    ]);
  });
});

describe("moveEntry", () => {
  const list: LayoutEntry[] = [
    { widgetId: "a", size: { cols: 4, rows: 1 } },
    { widgetId: "b", size: { cols: 2, rows: 2 } },
  ];

  it("reorders and returns a new array", () => {
    const moved = moveEntry(list, 0, 1);
    expect(moved.map((e) => e.widgetId)).toEqual(["b", "a"]);
    expect(moved).not.toBe(list);
  });

  it("is a no-op for equal or out-of-range indices", () => {
    expect(moveEntry(list, 1, 1)).toBe(list);
    expect(moveEntry(list, 0, 5)).toBe(list);
  });
});
