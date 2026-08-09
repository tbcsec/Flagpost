// Pure dashboard-layout logic (ARCHITECTURE.md §10.2–10.5, issue #21), split out
// from the grid component so it's unit-testable the way lib/automation-builder.ts
// is. No React, no react-grid-layout import, no data fetching — just the
// transforms between the persisted wire shape, the code-defined default, and the
// in-memory 2D layout the grid renders.

import type { LayoutEntry, WidgetDef } from "@/lib/dashboard/registry";
import type { DashboardLayoutEntry } from "@/lib/types";

/** The dashboard grid is 12 columns wide (issue #21). */
export const GRID_COLS = 12;

/** A react-grid-layout item — the structural shape RGL's `layouts`/`onLayoutChange`
 *  speak. Declared here (rather than importing RGL's type) so this module stays
 *  dependency-free and testable under plain vitest. */
export interface GridItem {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
  minW: number;
  minH: number;
}

const clamp = (n: number, lo: number, hi: number): number =>
  Math.max(lo, Math.min(hi, n));

const isNum = (n: unknown): n is number =>
  typeof n === "number" && Number.isFinite(n);

/** A saved entry is in the current 2D shape only if x/y/w/h are all real numbers.
 *  Anything else — notably the pre-#21 `{cols, rows}` shape — is treated as
 *  unrecognized and reset to the widget's default (issue #21 backward-compat:
 *  old ordered-flow layouts can't be mapped to 2D coordinates, so they're
 *  discarded rather than mis-converted). */
function isValidSaved(s: DashboardLayoutEntry): boolean {
  return isNum(s?.x) && isNum(s?.y) && isNum(s?.w) && isNum(s?.h);
}

/** Snap an entry to whole cells and clamp it into the grid: width ≥ the widget's
 *  minimum and ≤ the grid width, height ≥ minimum, and the position kept on-grid.
 *  This is the single guard that "resize is constrained to the registry minimum"
 *  (owner decision) — applied to saved data, keyboard nudges, and drag results. */
export function clampEntry(def: WidgetDef, e: LayoutEntry): LayoutEntry {
  const w = clamp(Math.round(e.w), def.minSize.w, GRID_COLS);
  const h = Math.max(Math.round(e.h), def.minSize.h);
  const x = clamp(Math.round(e.x), 0, GRID_COLS - w);
  const y = Math.max(0, Math.round(e.y));
  return { widgetId: e.widgetId, x, y, w, h, hidden: e.hidden };
}

/** Merge a saved layout with the registry into the entries the grid renders.
 *  - `null` saved (no customization yet) → the code default, cloned (§10.5).
 *  - Drops entries whose widget no longer exists (uninstalled/renamed).
 *  - Drops entries not in the 2D shape (pre-#21 saves) — they reset to default.
 *  - Clamps each surviving entry to the widget's min size and the grid bounds.
 *  - Appends any default widgets missing from the save (widgets added to the
 *    registry since the user last saved) so new widgets surface. */
export function mergeLayout(
  saved: DashboardLayoutEntry[] | null,
  def: LayoutEntry[],
  registry: Record<string, WidgetDef>,
): LayoutEntry[] {
  if (saved == null) return def.map((e) => ({ ...e }));

  const merged: LayoutEntry[] = [];
  const seen = new Set<string>();
  for (const s of saved) {
    const widget = registry[s.widget_id];
    if (!widget || seen.has(s.widget_id) || !isValidSaved(s)) continue;
    seen.add(s.widget_id);
    merged.push(
      clampEntry(widget, {
        widgetId: s.widget_id,
        x: s.x,
        y: s.y,
        w: s.w,
        h: s.h,
        hidden: Boolean(s.hidden),
      }),
    );
  }
  for (const e of def) {
    if (!seen.has(e.widgetId) && registry[e.widgetId]) {
      merged.push({ ...e });
    }
  }
  return merged;
}

/** Serialize in-memory entries to the persisted wire shape (§10.3). */
export function toSaved(entries: LayoutEntry[]): DashboardLayoutEntry[] {
  return entries.map((e) => ({
    widget_id: e.widgetId,
    x: e.x,
    y: e.y,
    w: e.w,
    h: e.h,
    hidden: Boolean(e.hidden),
  }));
}

/** Project entries into react-grid-layout items, carrying each widget's min size
 *  so RGL enforces the floor during drag/resize too (belt-and-braces with
 *  `clampEntry`). */
export function toGridItems(
  entries: LayoutEntry[],
  registry: Record<string, WidgetDef>,
): GridItem[] {
  return entries.map((e) => {
    const def = registry[e.widgetId];
    return {
      i: e.widgetId,
      x: e.x,
      y: e.y,
      w: e.w,
      h: e.h,
      minW: def?.minSize.w ?? 1,
      minH: def?.minSize.h ?? 1,
    };
  });
}

/** Fold react-grid-layout's updated positions (from `onLayoutChange`) back into
 *  the entries, preserving widget id, order and hidden state. */
export function applyGridItems(
  entries: LayoutEntry[],
  items: readonly Pick<GridItem, "i" | "x" | "y" | "w" | "h">[],
): LayoutEntry[] {
  const byId = new Map(items.map((it) => [it.i, it]));
  return entries.map((e) => {
    const it = byId.get(e.widgetId);
    return it ? { ...e, x: it.x, y: it.y, w: it.w, h: it.h } : e;
  });
}

/** Keyboard move fallback (RGL drag isn't keyboard-driveable): shift by whole
 *  cells, clamped on-grid. */
export function nudgeEntry(
  def: WidgetDef,
  e: LayoutEntry,
  dx: number,
  dy: number,
): LayoutEntry {
  return clampEntry(def, { ...e, x: e.x + dx, y: e.y + dy });
}

/** Keyboard resize fallback: grow/shrink by whole cells, clamped to min size and
 *  grid width. */
export function resizeEntry(
  def: WidgetDef,
  e: LayoutEntry,
  dw: number,
  dh: number,
): LayoutEntry {
  return clampEntry(def, { ...e, w: e.w + dw, h: e.h + dh });
}
