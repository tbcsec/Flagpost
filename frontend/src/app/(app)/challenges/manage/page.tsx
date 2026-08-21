"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import dynamic from "next/dynamic";

import { NoCompetition } from "@/components/app/no-competition";
import { SectionHeader } from "@/components/app/section-header";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useAccess } from "@/lib/hooks/use-permissions";

// The challenge authoring surface lives on its own route (reached from the
// "Manage challenges" action on /challenges) rather than expanding inline under
// the competitor grid — a master-detail editor needs the whole page, and a
// dedicated URL gives it a back button and a bookmark. Challenges are
// competition-scoped, so this stays in competition context (/challenges/manage),
// not the global /admin/* tree.
//
// ChallengeAdmin pulls the TipTap rich-text editor; loading it dynamically
// (ssr:false) keeps that weight off every other route's bundle.
const ChallengeAdmin = dynamic(
  () => import("@/components/challenges/challenge-admin").then((m) => m.ChallengeAdmin),
  { ssr: false, loading: () => <Skeleton className="h-64 w-full" /> },
);

export default function ManageChallengesPage() {
  const t = useTranslations("challenges");
  const ta = useTranslations("challenges.admin");
  const access = useAccess();
  const { competitionId, data: competition } = useActiveCompetition();

  if (!competitionId) {
    return <NoCompetition />;
  }

  return (
    <div className="flex flex-col gap-4">
      <Link
        href="/challenges"
        className="inline-flex w-fit items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <BackArrow />
        {t("backToChallenges")}
      </Link>

      <SectionHeader title={t("manage")} subtitle={competition?.name} />

      {!access.ready ? (
        <Skeleton className="h-64 w-full" />
      ) : access.canManageActiveCompetition ? (
        <ChallengeAdmin competitionId={competitionId} />
      ) : (
        <EmptyState title={ta("noAccessTitle")} description={ta("noAccessBody")} />
      )}
    </div>
  );
}

function BackArrow() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M19 12H5" />
      <path d="m12 19-7-7 7-7" />
    </svg>
  );
}
