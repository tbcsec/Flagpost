"use client";

import { useTranslations } from "next-intl";

import { NewAnnouncementDialog } from "@/components/announcements/new-announcement-dialog";
import { NoCompetition } from "@/components/app/no-competition";
import { SectionHeader } from "@/components/app/section-header";
import { DashboardGrid } from "@/components/dashboard/dashboard-grid";
import { FirstRunGuide } from "@/components/dashboard/first-run-guide";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveCompetition, useCompetitions } from "@/lib/hooks/use-competitions";
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
  const t = useTranslations("dashboard");
  const { competitionId, data: competition } = useActiveCompetition();
  const { data: competitions, isLoading: competitionsLoading } = useCompetitions();
  const access = useAccess();

  // Still resolving permissions or the competition list — a genuine loading state.
  if (!access.ready || competitionsLoading) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  // No active competition. If none exist at all, guide the user (a fresh install
  // has none) rather than spinning forever; if some exist the shell is just
  // defaulting the selection, so briefly show the skeleton.
  if (!competitionId) {
    if ((competitions?.length ?? 0) === 0) return <NoCompetition />;
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
        title={t("title")}
        subtitle={`${competition?.name ?? ""} · ${isManager ? t("subtitleManager") : t("subtitleParticipant")}`}
        actions={isManager ? <NewAnnouncementDialog competitionId={competitionId} /> : undefined}
      />

      {isManager && <FirstRunGuide competitionId={competitionId} />}

      <DashboardGrid
        competitionId={competitionId}
        dashboardKey="manager"
        defaultLayout={isManager ? DEFAULT_LAYOUT_MANAGER : DEFAULT_LAYOUT_PARTICIPANT}
        editable={canCustomize}
        audience={isManager ? "manager" : "participant"}
      />
    </>
  );
}
