"use client";

import { NewAnnouncementDialog } from "@/components/announcements/new-announcement-dialog";
import { SectionHeader } from "@/components/app/section-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useAccess } from "@/lib/hooks/use-permissions";
import {
  DEFAULT_LAYOUT_MANAGER,
  DEFAULT_LAYOUT_PARTICIPANT,
  WIDGETS,
} from "@/lib/dashboard/registry";

// The operational dashboard (ROADMAP #16). Renders a fixed-column grid plus the
// widgets in the current audience's layout (§10.1) — it never hardcodes which
// widget sits where; it just places each layout entry's widget at its declared
// column span. The manager and participant layouts come from the registry.
//
// Static so Tailwind keeps the classes; maps a widget's column span to its lg
// grid class (mobile stacks to one column).
const COL_SPAN: Record<number, string> = {
  1: "lg:col-span-1",
  2: "lg:col-span-2",
  3: "lg:col-span-3",
  4: "lg:col-span-4",
};

export default function DashboardPage() {
  const { competitionId, data: competition } = useActiveCompetition();
  const access = useAccess();

  if (!competitionId || !access.ready) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const isManager = access.canManageActiveCompetition;
  const layout = isManager ? DEFAULT_LAYOUT_MANAGER : DEFAULT_LAYOUT_PARTICIPANT;

  return (
    <>
      <SectionHeader
        title="Dashboard"
        subtitle={`${competition?.name ?? ""} · ${isManager ? "operational overview" : "your dashboard"}`}
        actions={isManager ? <NewAnnouncementDialog competitionId={competitionId} /> : undefined}
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-4 lg:items-start">
        {layout.map((entry) => {
          const def = WIDGETS[entry.widgetId];
          const Widget = def.Component;
          return (
            <div key={entry.widgetId} className={COL_SPAN[entry.size.cols] ?? "lg:col-span-4"}>
              <Widget competitionId={competitionId} />
            </div>
          );
        })}
      </div>
    </>
  );
}
