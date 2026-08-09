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

export interface WidgetDef {
  id: string;
  label: string; // shown in edit-mode chrome (§10.4)
  minSize: WidgetSize; // smallest the widget may be dragged down to (issue #21)
  defaultSize: WidgetSize; // size in the code-defined default layout
  Component: React.ComponentType<{ competitionId: string }>;
}

export const WIDGETS: Record<string, WidgetDef> = {
  stats: {
    id: "stats",
    label: "At a glance",
    minSize: { w: 4, h: 2 },
    defaultSize: { w: 12, h: 2 },
    Component: StatsWidget,
  },
  standing: {
    id: "standing",
    label: "Your standing",
    minSize: { w: 4, h: 2 },
    defaultSize: { w: 12, h: 2 },
    Component: StandingWidget,
  },
  activity: {
    id: "activity",
    label: "Recent solves",
    minSize: { w: 4, h: 3 },
    defaultSize: { w: 6, h: 5 },
    Component: ActivityWidget,
  },
  announcements: {
    id: "announcements",
    label: "Announcements",
    minSize: { w: 4, h: 3 },
    defaultSize: { w: 6, h: 5 },
    Component: AnnouncementsWidget,
  },
  "challenge-health": {
    id: "challenge-health",
    label: "Challenge health",
    minSize: { w: 4, h: 3 },
    defaultSize: { w: 6, h: 5 },
    Component: ChallengeHealthWidget,
  },
  "support-queue": {
    id: "support-queue",
    label: "Support queue",
    minSize: { w: 4, h: 3 },
    defaultSize: { w: 6, h: 5 },
    Component: SupportQueueWidget,
  },
  "my-solves": {
    id: "my-solves",
    label: "Your solves",
    minSize: { w: 4, h: 3 },
    defaultSize: { w: 6, h: 5 },
    Component: MySolvesWidget,
  },
};

export interface LayoutEntry {
  widgetId: string;
  x: number; // column offset (0-indexed) on the 12-column grid
  y: number; // row offset (0-indexed)
  w: number; // column span
  h: number; // row span
  hidden?: boolean; // customized-out but re-addable in edit mode (§10.4)
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
