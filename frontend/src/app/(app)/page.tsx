"use client";

import { NewAnnouncementDialog } from "@/components/announcements/new-announcement-dialog";
import { SectionHeader } from "@/components/app/section-header";
import { DashboardGrid } from "@/components/dashboard/dashboard-grid";
import { FirstRunGuide } from "@/components/dashboard/first-run-guide";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useAccess } from "@/lib/hooks/use-permissions";
import {
  DEFAULT_LAYOUT_MANAGER,
  DEFAULT_LAYOUT_PARTICIPANT,
} from "@/lib/dashboard/registry";

// The operational dashboard (ROADMAP #16, §10). Renders the audience's widgets
// through the registry-driven grid (§10.1) — never a hardcoded widget order.
// Managers (customize_dashboard) get the drag/resize/hide edit mode (Phase 6);
// participants get the fixed default layout.
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
  const canCustomize = isManager && access.has("customize_dashboard");

  return (
    <>
      <SectionHeader
        title="Dashboard"
        subtitle={`${competition?.name ?? ""} · ${isManager ? "operational overview" : "your dashboard"}`}
        actions={isManager ? <NewAnnouncementDialog competitionId={competitionId} /> : undefined}
      />

      {isManager && <FirstRunGuide competitionId={competitionId} />}

      <DashboardGrid
        competitionId={competitionId}
        dashboardKey="manager"
        defaultLayout={isManager ? DEFAULT_LAYOUT_MANAGER : DEFAULT_LAYOUT_PARTICIPANT}
        editable={canCustomize}
      />
    </>
  );
}
