// Pure dashboard-layout logic (ARCHITECTURE.md §10.2–10.5), split out from the
// page so it's unit-testable the way lib/automation-builder.ts is. No React,
// no data fetching — just the transforms between the persisted wire shape, the
// code-defined default, and the in-memory layout the grid renders.

import type { LayoutEntry, WidgetDef, WidgetSize } from "@/lib/dashboard/registry";
import type { DashboardLayoutEntry } from "@/lib/types";

const sameSize = (a: WidgetSize, b: WidgetSize) => a.cols === b.cols && a.rows === b.rows;

/** Snap a possibly-stale saved size to one this widget still declares legitimate
 *  (§10.2) — a widget's size set can change between saves; never render at a
 *  size the widget was not designed for. Falls back to the widget's default. */
function legitimateSize(def: WidgetDef, size: WidgetSize): WidgetSize {
  return def.sizes.find((s) => sameSize(s, size)) ?? def.defaultSize;
}

/** Cycle a widget to the next legitimate size (§10.4) — the "resize" affordance
 *  steps through the declared set rather than free-dragging a corner. Wraps. */
export function cycleSize(def: WidgetDef, current: WidgetSize): WidgetSize {
  const i = def.sizes.findIndex((s) => sameSize(s, current));
  if (i === -1) return def.sizes[0];
  return def.sizes[(i + 1) % def.sizes.length];
}

/** Merge a saved layout with the registry into the entries the grid renders.
 *  - `null` saved (no customization yet) → the code default, unchanged (§10.5).
 *  - Drops entries whose widget no longer exists (uninstalled/renamed).
 *  - Snaps each saved size back into the widget's legitimate set.
 *  - Appends any default widgets missing from the save (widgets added to the
 *    registry since the user last saved) so new widgets surface rather than
 *    staying invisible until a reset. */
export function mergeLayout(
  saved: DashboardLayoutEntry[] | null,
  def: LayoutEntry[],
  registry: Record<string, WidgetDef>,
): LayoutEntry[] {
  if (saved == null) return def.map((e) => ({ ...e, size: { ...e.size } }));

  const merged: LayoutEntry[] = [];
  const seen = new Set<string>();
  for (const s of saved) {
    const widget = registry[s.widget_id];
    if (!widget || seen.has(s.widget_id)) continue;
    seen.add(s.widget_id);
    merged.push({
      widgetId: s.widget_id,
      size: legitimateSize(widget, { cols: s.cols, rows: s.rows }),
      hidden: Boolean(s.hidden),
    });
  }
  for (const e of def) {
    if (!seen.has(e.widgetId) && registry[e.widgetId]) {
      merged.push({ ...e, size: { ...e.size } });
    }
  }
  return merged;
}

/** Serialize in-memory entries to the persisted wire shape (§10.3). */
export function toSaved(entries: LayoutEntry[]): DashboardLayoutEntry[] {
  return entries.map((e) => ({
    widget_id: e.widgetId,
    cols: e.size.cols,
    rows: e.size.rows,
    hidden: Boolean(e.hidden),
  }));
}

/** Move the entry at `from` to `to`, returning a new array (drag reorder). */
export function moveEntry(entries: LayoutEntry[], from: number, to: number): LayoutEntry[] {
  if (from === to || from < 0 || to < 0 || from >= entries.length || to >= entries.length) {
    return entries;
  }
  const next = entries.slice();
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}
