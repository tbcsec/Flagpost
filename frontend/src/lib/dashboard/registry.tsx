// Dashboard widget registry (ARCHITECTURE.md §10.1).
//
// The load-bearing decision: dashboard sections are registered as widgets —
// each with an id, a component reference, a minimum size, and a default size —
// so the page renders "whatever widget ids are in the layout, at their size",
// never a hardcoded `<StatsPanel/>` above `<Queue/>`. The layout is data, so the
// drag/resize/persistence layer is additive.
//
// Sizes are in units of a 12-column grid (issue #21): free-form corner-drag
// resize is snapped to whole cells and clamped to each widget's `minSize`. `w`
// is a column span (1–12); `h` is a row span (each row is a fixed pixel height,
// see ROW_HEIGHT in dashboard-grid).

import {
  ActivityWidget,
  AnnouncementsWidget,
  ChallengeHealthWidget,
  MySolvesWidget,
  StandingWidget,
  StatsWidget,
  SupportQueueWidget,
} from "@/components/dashboard/widgets";

/** A size in 12-column grid units: `w` columns wide, `h` rows tall. */
export interface WidgetSize {
  w: number;
  h: number;
}

/** Key into `dashboard.widgetLabels.*` / `dashboard.widgetDescriptions.*` — the
 *  edit-chrome name and the Add-section card copy are resolved with `t()` in the
 *  UI (§10.4), so the registry stays free of display strings. */
export type WidgetLabelKey =
  | "stats"
  | "standing"
  | "activity"
  | "announcements"
  | "challengeHealth"
  | "supportQueue"
  | "mySolves";

/** Which dashboard a section belongs on. The Add-section catalog (#330) is
 *  filtered by the current dashboard's audience, so competitor-personal sections
 *  (`standing`, `my-solves`) never surface on the manager dashboard's catalog and
 *  vice-versa. A section neutral to both (e.g. `announcements`) tags both. Only
 *  the manager dashboard is customizable today; the tag also sets up a future
 *  participant catalog cleanly. */
export type DashboardAudience = "manager" | "participant";

export interface WidgetDef {
  id: string;
  labelKey: WidgetLabelKey; // shown in edit-mode chrome (§10.4), via t()
  audiences: DashboardAudience[]; // which dashboards may add this section (#330)
  minSize: WidgetSize; // smallest the widget may be dragged down to (issue #21)
  defaultSize: WidgetSize; // size in the code-defined default layout
  Component: React.ComponentType<{ competitionId: string }>;
}

export const WIDGETS: Record<string, WidgetDef> = {
  stats: {
    id: "stats",
    labelKey: "stats",
    audiences: ["manager"],
    minSize: { w: 4, h: 2 },
    defaultSize: { w: 12, h: 2 },
    Component: StatsWidget,
  },
  standing: {
    id: "standing",
    labelKey: "standing",
    audiences: ["participant"],
    minSize: { w: 4, h: 2 },
    defaultSize: { w: 12, h: 2 },
    Component: StandingWidget,
  },
  activity: {
    id: "activity",
    labelKey: "activity",
    audiences: ["manager", "participant"],
    minSize: { w: 4, h: 3 },
    defaultSize: { w: 6, h: 5 },
    Component: ActivityWidget,
  },
  announcements: {
    id: "announcements",
    labelKey: "announcements",
    audiences: ["manager", "participant"],
    minSize: { w: 4, h: 3 },
    defaultSize: { w: 6, h: 5 },
    Component: AnnouncementsWidget,
  },
  "challenge-health": {
    id: "challenge-health",
    labelKey: "challengeHealth",
    audiences: ["manager"],
    minSize: { w: 4, h: 3 },
    defaultSize: { w: 6, h: 5 },
    Component: ChallengeHealthWidget,
  },
  "support-queue": {
    id: "support-queue",
    labelKey: "supportQueue",
    audiences: ["manager"],
    minSize: { w: 4, h: 3 },
    defaultSize: { w: 6, h: 5 },
    Component: SupportQueueWidget,
  },
  "my-solves": {
    id: "my-solves",
    labelKey: "mySolves",
    audiences: ["participant"],
    minSize: { w: 4, h: 3 },
    defaultSize: { w: 6, h: 5 },
    Component: MySolvesWidget,
  },
};

/** The sections a given dashboard audience may add (#330) — used to build the
 *  Add-section catalog. Order = the registry's declared order. */
export function widgetsForAudience(audience: DashboardAudience): WidgetDef[] {
  return Object.values(WIDGETS).filter((w) => w.audiences.includes(audience));
}

export interface LayoutEntry {
  widgetId: string;
  x: number; // column offset (0-indexed) on the 12-column grid
  y: number; // row offset (0-indexed)
  w: number; // column span
  h: number; // row span
  // A section is present iff it has an entry (#330). There is no in-memory
  // "hidden" any more — the customize UX adds/removes entries instead.
}

/** A default-layout entry: a widget placed at (x, y) at its default size. */
const at = (id: string, x: number, y: number): LayoutEntry => ({
  widgetId: id,
  x,
  y,
  w: WIDGETS[id].defaultSize.w,
  h: WIDGETS[id].defaultSize.h,
});

/** Fixed default layouts per audience (§10.1). Managers see operational
 *  widgets; competitors see their own standing and solves. Positions are 2D
 *  coordinates on the 12-column grid (a full-width band up top, then pairs). */
export const DEFAULT_LAYOUT_MANAGER: LayoutEntry[] = [
  at("stats", 0, 0),
  at("activity", 0, 2),
  at("announcements", 6, 2),
  at("challenge-health", 0, 7),
  at("support-queue", 6, 7),
];

export const DEFAULT_LAYOUT_PARTICIPANT: LayoutEntry[] = [
  at("standing", 0, 0),
  at("my-solves", 0, 2),
  at("announcements", 6, 2),
];
