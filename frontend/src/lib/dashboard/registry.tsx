// Dashboard widget registry (ARCHITECTURE.md §10.1).
//
// The load-bearing decision: dashboard sections are registered as widgets —
// each with an id, a component reference, and its set of legitimate sizes — so
// the page renders "whatever widget ids are in the layout, at their size",
// never a hardcoded `<StatsPanel/>` above `<Queue/>`. Tier 2 ships a FIXED
// per-audience default layout (no drag-drop UI yet, §10.2), but because the
// layout is data the drag-drop/persistence layer is additive, not a rewrite.

import {
  ActivityWidget,
  AnnouncementsWidget,
  ChallengeHealthWidget,
  MySolvesWidget,
  StandingWidget,
  StatsWidget,
  SupportQueueWidget,
} from "@/components/dashboard/widgets";

/** A size in grid units. `cols` drives width now; `rows` is declared for the
 *  future resize layer (§10.2) but not yet applied under the fixed layout. */
export interface WidgetSize {
  cols: number;
  rows: number;
}

export interface WidgetDef {
  id: string;
  sizes: WidgetSize[]; // legitimate sizes this widget renders at (§10.2)
  defaultSize: WidgetSize;
  Component: React.ComponentType<{ competitionId: string }>;
}

export const WIDGETS: Record<string, WidgetDef> = {
  stats: {
    id: "stats",
    sizes: [{ cols: 4, rows: 1 }],
    defaultSize: { cols: 4, rows: 1 },
    Component: StatsWidget,
  },
  standing: {
    id: "standing",
    sizes: [{ cols: 4, rows: 1 }, { cols: 2, rows: 1 }],
    defaultSize: { cols: 4, rows: 1 },
    Component: StandingWidget,
  },
  activity: {
    id: "activity",
    sizes: [{ cols: 2, rows: 2 }, { cols: 4, rows: 2 }],
    defaultSize: { cols: 2, rows: 2 },
    Component: ActivityWidget,
  },
  announcements: {
    id: "announcements",
    sizes: [{ cols: 2, rows: 2 }, { cols: 4, rows: 2 }],
    defaultSize: { cols: 2, rows: 2 },
    Component: AnnouncementsWidget,
  },
  "challenge-health": {
    id: "challenge-health",
    sizes: [{ cols: 2, rows: 2 }, { cols: 4, rows: 2 }],
    defaultSize: { cols: 2, rows: 2 },
    Component: ChallengeHealthWidget,
  },
  "support-queue": {
    id: "support-queue",
    sizes: [{ cols: 2, rows: 2 }, { cols: 4, rows: 2 }],
    defaultSize: { cols: 2, rows: 2 },
    Component: SupportQueueWidget,
  },
  "my-solves": {
    id: "my-solves",
    sizes: [{ cols: 2, rows: 2 }, { cols: 4, rows: 2 }],
    defaultSize: { cols: 2, rows: 2 },
    Component: MySolvesWidget,
  },
};

export interface LayoutEntry {
  widgetId: string;
  size: WidgetSize;
}

const at = (id: string): LayoutEntry => ({ widgetId: id, size: WIDGETS[id].defaultSize });

/** Fixed default layouts per audience (§10.1). Managers see operational
 *  widgets; competitors see their own standing and solves. */
export const DEFAULT_LAYOUT_MANAGER: LayoutEntry[] = [
  at("stats"),
  at("activity"),
  at("announcements"),
  at("challenge-health"),
  at("support-queue"),
];

export const DEFAULT_LAYOUT_PARTICIPANT: LayoutEntry[] = [
  at("standing"),
  at("my-solves"),
  at("announcements"),
];
