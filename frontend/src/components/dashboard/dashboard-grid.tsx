"use client";

// The customizable dashboard grid (ARCHITECTURE.md §10.2–10.5). Renders the
// registry widgets in the user's saved order/size, and — for a manager who
// holds `customize_dashboard` — an edit mode with drag-to-reorder, a size-cycle
// control stepping each widget through its declared legitimate sizes, show/hide,
// and explicit Save / Cancel / Reset-to-default (saving is on exit-edit, not per
// drag, §10.3). Non-editable audiences (participants) get the plain fixed
// render, no fetch. Native HTML5 drag-and-drop — Flagpost ships no DnD library.

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type LayoutEntry, WIDGETS } from "@/lib/dashboard/registry";
import { cycleSize, mergeLayout, moveEntry, toSaved } from "@/lib/dashboard/layout";
import {
  useDashboardLayout,
  useResetDashboardLayout,
  useSaveDashboardLayout,
} from "@/lib/hooks/use-dashboard";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast";

// Static so Tailwind keeps the classes; maps a widget's column span to its lg
// grid class (mobile stacks to one column).
const COL_SPAN: Record<number, string> = {
  1: "lg:col-span-1",
  2: "lg:col-span-2",
  3: "lg:col-span-3",
  4: "lg:col-span-4",
};

const gripIcon = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden><circle cx="9" cy="6" r="1.6" /><circle cx="15" cy="6" r="1.6" /><circle cx="9" cy="12" r="1.6" /><circle cx="15" cy="12" r="1.6" /><circle cx="9" cy="18" r="1.6" /><circle cx="15" cy="18" r="1.6" /></svg>
);
const resizeIcon = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M15 3h6v6" /><path d="M9 21H3v-6" /><path d="M21 3l-7 7" /><path d="M3 21l7-7" /></svg>
);
const eyeIcon = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="3" /></svg>
);
const eyeOffIcon = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M9.9 4.24A9.1 9.1 0 0 1 12 4c6.5 0 10 7 10 7a13 13 0 0 1-2.16 2.92" /><path d="M6.6 6.6A13 13 0 0 0 2 11s3.5 7 10 7a9 9 0 0 0 5.4-1.6" /><path d="M3 3l18 18" /></svg>
);

interface DashboardGridProps {
  competitionId: string;
  dashboardKey: string;
  defaultLayout: LayoutEntry[];
  editable: boolean;
}

export function DashboardGrid({
  competitionId,
  dashboardKey,
  defaultLayout,
  editable,
}: DashboardGridProps) {
  const layoutQuery = useDashboardLayout(competitionId, dashboardKey, editable);
  const saveLayout = useSaveDashboardLayout(competitionId, dashboardKey);
  const resetLayout = useResetDashboardLayout(competitionId, dashboardKey);

  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState<LayoutEntry[]>([]);
  const [dragIndex, setDragIndex] = React.useState<number | null>(null);

  // The committed layout = saved (merged with the registry) or the code default.
  const committed = React.useMemo(
    () => mergeLayout(layoutQuery.data?.entries ?? null, defaultLayout, WIDGETS),
    [layoutQuery.data, defaultLayout],
  );

  // Non-editable audiences render the fixed default with no chrome or fetch.
  if (!editable) {
    return <Grid entries={defaultLayout.filter((e) => !e.hidden)} competitionId={competitionId} />;
  }

  if (layoutQuery.isLoading) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const startEditing = () => {
    setDraft(committed.map((e) => ({ ...e, size: { ...e.size } })));
    setEditing(true);
  };

  const save = () => {
    saveLayout.mutate(toSaved(draft), {
      onSuccess: () => {
        setEditing(false);
        toast("Dashboard layout saved", { variant: "success" });
      },
      onError: () => toast("Couldn't save layout", { variant: "destructive" }),
    });
  };

  const reset = () => {
    resetLayout.mutate(undefined, {
      onSuccess: () => {
        setEditing(false);
        toast("Dashboard reset to default");
      },
      onError: () => toast("Couldn't reset layout", { variant: "destructive" }),
    });
  };

  const cycle = (index: number) => {
    setDraft((d) =>
      d.map((e, i) =>
        i === index ? { ...e, size: cycleSize(WIDGETS[e.widgetId], e.size) } : e,
      ),
    );
  };

  const toggleHidden = (index: number) => {
    setDraft((d) => d.map((e, i) => (i === index ? { ...e, hidden: !e.hidden } : e)));
  };

  const onDragEnter = (index: number) => {
    if (dragIndex === null || dragIndex === index) return;
    setDraft((d) => moveEntry(d, dragIndex, index));
    setDragIndex(index);
  };

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {!editing ? (
          <Button variant="outline" size="sm" onClick={startEditing}>
            Customize
          </Button>
        ) : (
          <>
            <span className="mr-1 text-sm text-muted-foreground">
              Drag to reorder · resize or hide each widget
            </span>
            <Button size="sm" onClick={save} disabled={saveLayout.isPending}>
              {saveLayout.isPending ? "Saving…" : "Save layout"}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={reset}
              disabled={resetLayout.isPending}
              className="text-muted-foreground"
            >
              Reset to default
            </Button>
          </>
        )}
      </div>

      {editing ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-4 lg:items-start">
          {draft.map((entry, index) => (
            <EditableWidget
              key={entry.widgetId}
              entry={entry}
              competitionId={competitionId}
              isDragging={dragIndex === index}
              onDragStart={() => setDragIndex(index)}
              onDragEnter={() => onDragEnter(index)}
              onDragEnd={() => setDragIndex(null)}
              onCycle={() => cycle(index)}
              onToggleHidden={() => toggleHidden(index)}
            />
          ))}
        </div>
      ) : (
        <Grid entries={committed.filter((e) => !e.hidden)} competitionId={competitionId} />
      )}
    </div>
  );
}

/** Read-only render of a set of layout entries. */
function Grid({ entries, competitionId }: { entries: LayoutEntry[]; competitionId: string }) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-4 lg:items-start">
      {entries.map((entry) => {
        const def = WIDGETS[entry.widgetId];
        if (!def) return null;
        const Widget = def.Component;
        return (
          <div key={entry.widgetId} className={COL_SPAN[entry.size.cols] ?? "lg:col-span-4"}>
            <Widget competitionId={competitionId} />
          </div>
        );
      })}
    </div>
  );
}

interface EditableWidgetProps {
  entry: LayoutEntry;
  competitionId: string;
  isDragging: boolean;
  onDragStart: () => void;
  onDragEnter: () => void;
  onDragEnd: () => void;
  onCycle: () => void;
  onToggleHidden: () => void;
}

/** A widget in edit mode: draggable, with a size-cycle and hide control, and a
 *  shield over its content so clicks rearrange rather than interact (§10.4). */
function EditableWidget({
  entry,
  competitionId,
  isDragging,
  onDragStart,
  onDragEnter,
  onDragEnd,
  onCycle,
  onToggleHidden,
}: EditableWidgetProps) {
  const def = WIDGETS[entry.widgetId];
  if (!def) return null;
  const Widget = def.Component;
  const label = `${entry.size.cols}×${entry.size.rows}`;
  const canResize = def.sizes.length > 1;

  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        onDragStart();
      }}
      onDragEnter={onDragEnter}
      onDragOver={(e) => e.preventDefault()}
      onDragEnd={onDragEnd}
      className={cn(
        "relative rounded-lg border-2 border-dashed border-primary/40 p-1 transition-opacity",
        COL_SPAN[entry.size.cols] ?? "lg:col-span-4",
        isDragging && "opacity-40",
        entry.hidden && "opacity-50",
      )}
    >
      {/* Edit chrome — above the shield so its controls stay clickable. */}
      <div className="absolute inset-x-1 top-1 z-20 flex items-center justify-between rounded-t-md bg-background/80 px-2 py-1 backdrop-blur">
        <span
          className="flex cursor-grab items-center gap-1.5 text-xs font-medium text-muted-foreground active:cursor-grabbing"
          aria-label="Drag to reorder"
        >
          {gripIcon}
          {def.label}
          {entry.hidden && <span className="italic">· hidden</span>}
        </span>
        <span className="flex items-center gap-1">
          {canResize && (
            <button
              type="button"
              onClick={onCycle}
              className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              aria-label={`Resize ${def.label} (currently ${label})`}
            >
              {resizeIcon}
              <span className="tabular-nums">{label}</span>
            </button>
          )}
          <button
            type="button"
            onClick={onToggleHidden}
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            aria-label={entry.hidden ? `Show ${def.label}` : `Hide ${def.label}`}
          >
            {entry.hidden ? eyeOffIcon : eyeIcon}
          </button>
        </span>
      </div>

      {/* Click shield — clicks in edit mode rearrange, not interact (§10.4). */}
      <div className="absolute inset-0 z-10" aria-hidden />

      <div className="pointer-events-none pt-8">
        <Widget competitionId={competitionId} />
      </div>
    </div>
  );
}
