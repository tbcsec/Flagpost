"use client";

// The customizable dashboard grid (ARCHITECTURE.md §10.2–10.5, issue #21).
// Renders the registry widgets in the user's saved 2D layout, and — for a
// manager who holds `customize_dashboard` — an edit mode with fluid
// drag-to-move and free corner-resize (constrained to each widget's registry
// minimum), show/hide, and explicit Save / Cancel / Reset-to-default (saving is
// on exit-edit, not per drag, §10.3). Powered by react-grid-layout (its 2.x core
// is React-19-safe; we use the classic `legacy` API surface). Non-editable
// audiences (participants) get the plain static render, no layout fetch.

import { useTranslations } from "next-intl";
import * as React from "react";
import { Responsive, WidthProvider } from "react-grid-layout/legacy";
import type { Layout, ResponsiveLayouts } from "react-grid-layout/legacy";

import "react-grid-layout/css/styles.css";
import "@/components/dashboard/dashboard-grid.css";

import { AddSectionModal } from "@/components/dashboard/add-section-modal";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type DashboardAudience,
  type LayoutEntry,
  WIDGETS,
} from "@/lib/dashboard/registry";
import {
  addEntry,
  applyGridItems,
  mergeLayout,
  nudgeEntry,
  resizeEntry,
  toGridItems,
  toSaved,
} from "@/lib/dashboard/layout";
import {
  useDashboardLayout,
  useResetDashboardLayout,
  useSaveDashboardLayout,
} from "@/lib/hooks/use-dashboard";
import { toast } from "@/stores/toast";

// Recreating the HOC each render would remount the grid, so build it once.
const ResponsiveGridLayout = WidthProvider(Responsive);

// A row is a fixed pixel height; `h` grid units × this drives a widget's height.
const ROW_HEIGHT = 60;
const MARGIN: [number, number] = [16, 16];
// Desktop: the full 12-column grid. Below `sm`: a single stacked column, so the
// dashboard stays usable on a phone (RGL reflows every item to full width).
const BREAKPOINTS = { lg: 768, sm: 0 };
const COLS = { lg: 12, sm: 1 };

const gripIcon = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden><circle cx="9" cy="6" r="1.6" /><circle cx="15" cy="6" r="1.6" /><circle cx="9" cy="12" r="1.6" /><circle cx="15" cy="12" r="1.6" /><circle cx="9" cy="18" r="1.6" /><circle cx="15" cy="18" r="1.6" /></svg>
);
const removeIcon = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M18 6 6 18" /><path d="m6 6 12 12" /></svg>
);

interface DashboardGridProps {
  competitionId: string;
  dashboardKey: string;
  defaultLayout: LayoutEntry[];
  editable: boolean;
  // Which dashboard this is — scopes the Add-section catalog (#330). Only the
  // manager dashboard is editable today, so in practice this is "manager".
  audience: DashboardAudience;
}

/** Positions equal? (order is preserved by applyGridItems, so compare pairwise.) */
function geomEqual(a: LayoutEntry[], b: LayoutEntry[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].x !== b[i].x || a[i].y !== b[i].y || a[i].w !== b[i].w || a[i].h !== b[i].h) {
      return false;
    }
  }
  return true;
}

export function DashboardGrid({
  competitionId,
  dashboardKey,
  defaultLayout,
  editable,
  audience,
}: DashboardGridProps) {
  const t = useTranslations("dashboard.grid");
  const layoutQuery = useDashboardLayout(competitionId, dashboardKey, editable);
  const saveLayout = useSaveDashboardLayout(competitionId, dashboardKey);
  const resetLayout = useResetDashboardLayout(competitionId, dashboardKey);

  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState<LayoutEntry[]>([]);
  // react-grid-layout measures the DOM, so it must only run on the client. This
  // reads false on the server / initial hydration and true once mounted (no
  // effect, no hydration mismatch), so SSR/prerender (npm run build) renders the
  // skeleton, never RGL.
  const mounted = React.useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );

  // The committed layout = saved (merged with the registry) or the code default.
  const committed = React.useMemo(
    () => mergeLayout(layoutQuery.data?.entries ?? null, defaultLayout, WIDGETS),
    [layoutQuery.data, defaultLayout],
  );

  const loadingSkeleton = (
    <div className="grid gap-4">
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );

  if (!mounted) return loadingSkeleton;

  // Non-editable audiences render the fixed default statically, with no fetch.
  if (!editable) {
    return <StaticGrid entries={defaultLayout} competitionId={competitionId} />;
  }

  if (layoutQuery.isLoading) return loadingSkeleton;

  const startEditing = () => {
    setDraft(committed.map((e) => ({ ...e })));
    setEditing(true);
  };

  const save = () => {
    saveLayout.mutate(toSaved(draft), {
      onSuccess: () => {
        setEditing(false);
        toast(t("savedToast"), { variant: "success" });
      },
      onError: () => toast(t("saveErrorToast"), { variant: "destructive" }),
    });
  };

  const reset = () => {
    resetLayout.mutate(undefined, {
      onSuccess: () => {
        setEditing(false);
        toast(t("resetToast"));
      },
      onError: () => toast(t("resetErrorToast"), { variant: "destructive" }),
    });
  };

  // RGL hands back the full updated layout on any drag/resize; fold it into the
  // draft (preserving widget id / order / hidden). Guarded so an unchanged
  // layout doesn't churn state.
  const onLayoutChange = (current: Layout, all: ResponsiveLayouts) => {
    const items = all?.lg ?? current;
    if (!items) return;
    setDraft((d) => {
      const next = applyGridItems(d, items);
      return geomEqual(d, next) ? d : next;
    });
  };

  const add = (widgetId: string) =>
    setDraft((d) => (WIDGETS[widgetId] ? addEntry(d, WIDGETS[widgetId]) : d));
  const remove = (index: number) =>
    setDraft((d) => d.filter((_, i) => i !== index));
  const nudge = (index: number, dx: number, dy: number) =>
    setDraft((d) =>
      d.map((e, i) => (i === index ? nudgeEntry(WIDGETS[e.widgetId], e, dx, dy) : e)),
    );
  const resize = (index: number, dw: number, dh: number) =>
    setDraft((d) =>
      d.map((e, i) => (i === index ? resizeEntry(WIDGETS[e.widgetId], e, dw, dh) : e)),
    );

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {!editing ? (
          <Button variant="outline" size="sm" onClick={startEditing}>
            {t("customize")}
          </Button>
        ) : (
          <>
            <span className="mr-1 text-sm text-muted-foreground">
              {t("editHint")}
            </span>
            <AddSectionModal audience={audience} present={draft} onAdd={add} />
            <Button size="sm" onClick={save} disabled={saveLayout.isPending}>
              {saveLayout.isPending ? t("saving") : t("saveLayout")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setEditing(false)}>
              {t("cancel")}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={reset}
              disabled={resetLayout.isPending}
              className="text-muted-foreground"
            >
              {t("resetDefault")}
            </Button>
          </>
        )}
      </div>

      {editing ? (
        <div className="dashboard-grid dashboard-grid--editing">
          <ResponsiveGridLayout
            layouts={{ lg: toGridItems(draft, WIDGETS) }}
            breakpoints={BREAKPOINTS}
            cols={COLS}
            rowHeight={ROW_HEIGHT}
            margin={MARGIN}
            containerPadding={[0, 0]}
            isDraggable
            isResizable
            isBounded
            compactType="vertical"
            useCSSTransforms
            draggableHandle=".rgl-drag-handle"
            resizeHandles={["se"]}
            onLayoutChange={onLayoutChange}
          >
            {draft.map((entry, index) => (
              <div key={entry.widgetId}>
                <EditableWidget
                  entry={entry}
                  competitionId={competitionId}
                  onRemove={() => remove(index)}
                  onNudge={(dx, dy) => nudge(index, dx, dy)}
                  onResize={(dw, dh) => resize(index, dw, dh)}
                />
              </div>
            ))}
          </ResponsiveGridLayout>
        </div>
      ) : (
        <StaticGrid entries={committed} competitionId={competitionId} />
      )}
    </div>
  );
}

/** Read-only render of a set of layout entries at their saved 2D positions.
 *  Static (no drag/resize); reflows to a single column below the `sm`
 *  breakpoint so it stays usable on a phone. */
function StaticGrid({
  entries,
  competitionId,
}: {
  entries: LayoutEntry[];
  competitionId: string;
}) {
  return (
    <div className="dashboard-grid">
      <ResponsiveGridLayout
        layouts={{ lg: toGridItems(entries, WIDGETS) }}
        breakpoints={BREAKPOINTS}
        cols={COLS}
        rowHeight={ROW_HEIGHT}
        margin={MARGIN}
        containerPadding={[0, 0]}
        isDraggable={false}
        isResizable={false}
        compactType="vertical"
        useCSSTransforms
      >
        {entries.map((entry) => {
          const def = WIDGETS[entry.widgetId];
          if (!def) return null;
          const Widget = def.Component;
          return (
            <div key={entry.widgetId}>
              <div className="h-full min-h-0 overflow-hidden">
                <Widget competitionId={competitionId} />
              </div>
            </div>
          );
        })}
      </ResponsiveGridLayout>
    </div>
  );
}

interface EditableWidgetProps {
  entry: LayoutEntry;
  competitionId: string;
  onRemove: () => void;
  onNudge: (dx: number, dy: number) => void;
  onResize: (dw: number, dh: number) => void;
}

/** A widget in edit mode: a drag handle (mouse) plus keyboard move/resize
 *  fallbacks (RGL's drag/resize can't be driven from the keyboard), a remove
 *  control (returns the section to the Add-section catalog, #330), and a
 *  pointer-events shield so clicks rearrange rather than interact with the
 *  widget's own controls (§10.4). */
function EditableWidget({
  entry,
  competitionId,
  onRemove,
  onNudge,
  onResize,
}: EditableWidgetProps) {
  const t = useTranslations("dashboard");
  const def = WIDGETS[entry.widgetId];
  if (!def) return null;
  const Widget = def.Component;
  const label = t(`widgetLabels.${def.labelKey}`);

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border-2 border-dashed border-primary/40 bg-background/40">
      {/* Edit chrome — above the shield so its controls stay clickable. */}
      <div className="flex flex-shrink-0 flex-wrap items-center justify-between gap-1 border-b border-border/60 bg-background/80 px-2 py-1 backdrop-blur">
        <span
          className="rgl-drag-handle flex cursor-grab items-center gap-1.5 text-xs font-medium text-muted-foreground active:cursor-grabbing"
          aria-label={t("grid.dragToMove", { label })}
        >
          {gripIcon}
          {label}
        </span>
        <span className="flex items-center gap-0.5">
          <ChromeGroup label={t("grid.groupMove")}>
            <ChromeButton label={t("grid.moveLeft", { label })} onClick={() => onNudge(-1, 0)}>←</ChromeButton>
            <ChromeButton label={t("grid.moveRight", { label })} onClick={() => onNudge(1, 0)}>→</ChromeButton>
            <ChromeButton label={t("grid.moveUp", { label })} onClick={() => onNudge(0, -1)}>↑</ChromeButton>
            <ChromeButton label={t("grid.moveDown", { label })} onClick={() => onNudge(0, 1)}>↓</ChromeButton>
          </ChromeGroup>
          <ChromeGroup label={t("grid.groupResize")}>
            <ChromeButton label={t("grid.narrower", { label })} onClick={() => onResize(-1, 0)}>−W</ChromeButton>
            <ChromeButton label={t("grid.wider", { label })} onClick={() => onResize(1, 0)}>+W</ChromeButton>
            <ChromeButton label={t("grid.shorter", { label })} onClick={() => onResize(0, -1)}>−H</ChromeButton>
            <ChromeButton label={t("grid.taller", { label })} onClick={() => onResize(0, 1)}>+H</ChromeButton>
          </ChromeGroup>
          <button
            type="button"
            onClick={onRemove}
            className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            aria-label={t("grid.remove", { label })}
          >
            {removeIcon}
          </button>
        </span>
      </div>

      {/* Shielded widget body — non-interactive in edit mode. */}
      <div className="pointer-events-none min-h-0 flex-1 overflow-hidden p-1">
        <Widget competitionId={competitionId} />
      </div>
    </div>
  );
}

function ChromeGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span
      className="mr-1 flex items-center gap-0.5 border-r border-border/60 pr-1"
      role="group"
      aria-label={label}
    >
      {children}
    </span>
  );
}

function ChromeButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="rounded px-1 py-0.5 text-[11px] font-medium tabular-nums text-muted-foreground hover:bg-accent hover:text-accent-foreground"
    >
      {children}
    </button>
  );
}
