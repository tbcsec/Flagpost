"use client";

import { useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";

import { NoCompetition } from "@/components/app/no-competition";
import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
import { SortableTableHead, TablePagination } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { parseServerDate } from "@/lib/datetime";
import { useChallenges } from "@/lib/hooks/use-challenges";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useDataTable } from "@/lib/hooks/use-data-table";
import { useAdminInstances, useKillInstance } from "@/lib/hooks/use-instances";
import { useParticipants } from "@/lib/hooks/use-participants";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useTeams } from "@/lib/hooks/use-teams";
import type { AdminInstance } from "@/lib/types";
import { toast } from "@/stores/toast";

// Running-instance ops (#266, ADR-0036). Every live challenge instance in the
// competition, with force-kill — gated on instance_view (read) / instance_manage
// (kill). Refreshes live over the activity room (lib/live.ts invalidates
// ["admin_instances", cid] on any challenge.instance_* event). The list carries
// ids only, so challenge/subject labels are resolved from the rosters already
// loaded elsewhere.

function statusVariant(status: string): "success" | "destructive" | "muted" {
  if (status === "running") return "success";
  if (status === "failed") return "destructive";
  return "muted";
}

/** An "in 12m" / "in 2h" / "due" label for a future expiry, relative to a `now`
 *  the page refreshes every 30s (one interval, not one per row). */
function ExpiresLabel({ iso, now }: { iso: string; now: number }) {
  const t = useTranslations("instances");
  const secs = Math.round((parseServerDate(iso).getTime() - now) / 1000);
  if (secs <= 0) return <>{t("expiresDue")}</>;
  const mins = Math.round(secs / 60);
  return (
    <>
      {mins < 60
        ? t("expiresInMin", { count: mins })
        : t("expiresInHour", { count: Math.round(mins / 60) })}
    </>
  );
}

export default function InstancesPage() {
  const t = useTranslations("instances");
  const tn = useTranslations("common.nouns");
  const { competitionId } = useActiveCompetition();
  const access = useAccess();
  const canView = access.has("instance_view");
  const canKill = access.has("instance_manage");
  const confirm = useConfirm();

  // A single clock the whole table's expiry labels read, refreshed every 30s
  // (Date.now() in the initializer/interval keeps it out of the render body).
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  const instances = useAdminInstances(competitionId ?? "", canView);
  const challenges = useChallenges(competitionId ?? "");
  const teams = useTeams(competitionId ?? "");
  const participants = useParticipants(competitionId ?? "", canView);
  const kill = useKillInstance(competitionId ?? "");

  const challengeTitle = useMemo(
    () => new Map((challenges.data ?? []).map((c) => [c.id, c.title])),
    [challenges.data],
  );
  const teamName = useMemo(
    () => new Map((teams.data ?? []).map((tm) => [tm.id, tm.name])),
    [teams.data],
  );
  const userName = useMemo(
    () => new Map((participants.data ?? []).map((p) => [p.user_id, p.display_name])),
    [participants.data],
  );

  const rows = instances.data ?? [];
  const subjectOf = (i: AdminInstance) =>
    i.team_id
      ? (teamName.get(i.team_id) ?? i.team_id)
      : (userName.get(i.user_id) ?? i.user_id);

  const table = useDataTable(rows, {
    columns: {
      challenge: (i: AdminInstance) => challengeTitle.get(i.challenge_id) ?? i.challenge_id,
      subject: subjectOf,
      status: (i: AdminInstance) => i.status,
      expires: { value: (i: AdminInstance) => i.expires_at ?? "", defaultDir: "asc" },
    },
  });
  const dir = (key: string) => (table.sort?.key === key ? table.sort.dir : null);

  if (!competitionId) return <NoCompetition />;
  if (!access.ready) return <Skeleton className="h-64 w-full" />;
  if (!canView) {
    return (
      <>
        <SectionHeader title={t("title")} subtitle={t("noAccessSubtitle")} />
        <EmptyState title={t("noAccessTitle")} description={t("noAccessDescription")} />
      </>
    );
  }

  async function onKill(instance: AdminInstance) {
    if (
      !(await confirm({
        title: t("killConfirmTitle"),
        description: t("killConfirmDescription"),
        confirmLabel: t("kill"),
      }))
    ) {
      return;
    }
    kill.mutate(instance.id, {
      onSuccess: () => toast(t("killed"), { variant: "success" }),
      onError: (e) =>
        toast(t("killFailed"), {
          description: (e as Error).message,
          variant: "destructive",
        }),
    });
  }

  return (
    <>
      <SectionHeader title={t("title")} subtitle={t("subtitle")} />

      {instances.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : instances.isError ? (
        <EmptyState title={t("unavailableTitle")} description={t("unavailableDescription")} />
      ) : rows.length === 0 ? (
        <EmptyState title={t("emptyTitle")} description={t("emptyDescription")} />
      ) : (
        <Card>
          <CardContent className="pt-5">
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableTableHead active={dir("challenge")} onSort={() => table.toggleSort("challenge")}>
                    {t("colChallenge")}
                  </SortableTableHead>
                  <SortableTableHead active={dir("subject")} onSort={() => table.toggleSort("subject")}>
                    {t("colSubject")}
                  </SortableTableHead>
                  <SortableTableHead active={dir("status")} onSort={() => table.toggleSort("status")}>
                    {t("colStatus")}
                  </SortableTableHead>
                  <SortableTableHead active={dir("expires")} onSort={() => table.toggleSort("expires")}>
                    {t("colExpires")}
                  </SortableTableHead>
                  <TableHead className="text-right">{t("colActions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {table.rows.map((i) => (
                  <TableRow key={i.id}>
                    <TableCell className="font-medium">
                      {challengeTitle.get(i.challenge_id) ?? i.challenge_id}
                    </TableCell>
                    <TableCell>{subjectOf(i)}</TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(i.status)}>{t(`status.${i.status}`)}</Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {i.expires_at ? <ExpiresLabel iso={i.expires_at} now={now} /> : "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right">
                      {canKill && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive"
                          disabled={kill.isPending}
                          onClick={() => onKill(i)}
                        >
                          {t("kill")}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <TablePagination table={table} noun={tn("instances")} className="mt-4" />
          </CardContent>
        </Card>
      )}
    </>
  );
}
