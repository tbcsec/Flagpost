import { describe, expect, it } from "vitest";

import {
  DEFAULT_LAYOUT_MANAGER,
  DEFAULT_LAYOUT_PARTICIPANT,
  WIDGETS,
  type WidgetSize,
} from "@/lib/dashboard/registry";

const sameSize = (a: WidgetSize, b: WidgetSize) =>
  a.cols === b.cols && a.rows === b.rows;

describe("dashboard widget registry", () => {
  it("every widget's default size is one of its legitimate sizes", () => {
    for (const def of Object.values(WIDGETS)) {
      expect(
        def.sizes.some((s) => sameSize(s, def.defaultSize)),
        `${def.id} default size not in sizes`,
      ).toBe(true);
    }
  });

  it("every layout entry references a registered widget at a legitimate size", () => {
    for (const entry of [...DEFAULT_LAYOUT_MANAGER, ...DEFAULT_LAYOUT_PARTICIPANT]) {
      const def = WIDGETS[entry.widgetId];
      expect(def, `unknown widget ${entry.widgetId}`).toBeDefined();
      expect(
        def.sizes.some((s) => sameSize(s, entry.size)),
        `${entry.widgetId} laid out at an illegitimate size`,
      ).toBe(true);
    }
  });

  it("column spans never exceed the 4-column grid", () => {
    for (const def of Object.values(WIDGETS)) {
      for (const size of def.sizes) {
        expect(size.cols).toBeGreaterThanOrEqual(1);
        expect(size.cols).toBeLessThanOrEqual(4);
      }
    }
  });
});
