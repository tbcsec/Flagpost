"use client";

import { useTranslations } from "next-intl";

import { NoCompetition } from "@/components/app/no-competition";
import { SectionHeader } from "@/components/app/section-header";
import { JudgingConsole } from "@/components/judge/judging-console";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useAccess } from "@/lib/hooks/use-permissions";

// The jury console (#450): every code judging in the competition, the queue,
// and rejudging / overriding — staff with judging_view (Judges have it), the
// actions with judging_rejudge.
export default function JudgingPage() {
  const t = useTranslations("judging");
  const { competitionId } = useActiveCompetition();
  const access = useAccess();
  if (!competitionId) return <NoCompetition />;
  if (!access.ready) return <Skeleton className="h-64 w-full" />;
  if (!access.has("judging_view")) {
    return (
      <>
        <SectionHeader title={t("title")} />
        <EmptyState title={t("noAccessTitle")} description={t("noAccessDescription")} />
      </>
    );
  }
  return (
    <>
      <SectionHeader title={t("title")} subtitle={t("subtitle")} />
      <JudgingConsole competitionId={competitionId} canAct={access.has("judging_rejudge")} />
    </>
  );
}
