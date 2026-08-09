import { describe, expect, it } from "vitest";

import {
  DEFAULT_LAYOUT_MANAGER,
  DEFAULT_LAYOUT_PARTICIPANT,
  WIDGETS,
} from "@/lib/dashboard/registry";
import { GRID_COLS } from "@/lib/dashboard/layout";

describe("dashboard widget registry", () => {
  it("every widget's default size is at least its minimum and fits the grid", () => {
    for (const def of Object.values(WIDGETS)) {
      expect(def.defaultSize.w, `${def.id} default width < min`).toBeGreaterThanOrEqual(def.minSize.w);
      expect(def.defaultSize.h, `${def.id} default height < min`).toBeGreaterThanOrEqual(def.minSize.h);
      expect(def.defaultSize.w, `${def.id} default width > grid`).toBeLessThanOrEqual(GRID_COLS);
      expect(def.minSize.w, `${def.id} min width off-grid`).toBeGreaterThanOrEqual(1);
      expect(def.minSize.w).toBeLessThanOrEqual(GRID_COLS);
      expect(def.minSize.h).toBeGreaterThanOrEqual(1);
    }
  });

  it("every default-layout entry references a registered widget and sits on-grid", () => {
    for (const entry of [...DEFAULT_LAYOUT_MANAGER, ...DEFAULT_LAYOUT_PARTICIPANT]) {
      const def = WIDGETS[entry.widgetId];
      expect(def, `unknown widget ${entry.widgetId}`).toBeDefined();
      expect(entry.w, `${entry.widgetId} laid out below its min width`).toBeGreaterThanOrEqual(def.minSize.w);
      expect(entry.h, `${entry.widgetId} laid out below its min height`).toBeGreaterThanOrEqual(def.minSize.h);
      expect(entry.x, `${entry.widgetId} starts off-grid`).toBeGreaterThanOrEqual(0);
      expect(entry.x + entry.w, `${entry.widgetId} overflows the grid width`).toBeLessThanOrEqual(GRID_COLS);
      expect(entry.y).toBeGreaterThanOrEqual(0);
    }
  });
});
