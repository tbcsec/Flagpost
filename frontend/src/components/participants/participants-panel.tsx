"use client";

// Individual-mode participant roster (§14 components/<domain>). The counterpart
// to TeamPanel for competitions without teams: a compact "you" summary plus the
// full roster with standing, all via the use-participants hook. Server state
// only; no client-side ranking (the backend reuses the scoreboard computation).

import { useTranslations } from "next-intl";
import { useState } from "react";

import { AwardDialog } from "@/components/participants/award-dialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  SortableTableHead,
  TablePagination,
  TableSearchInput,
} from "@/components/ui/data-table";
import { EmptyState, PeopleEmptyIcon } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDataTable } from "@/lib/hooks/use-data-table";
import { useParticipants } from "@/lib/hooks/use-participants";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import type { Participant } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";

export function ParticipantsPanel({ competitionId }: { competitionId: string }) {
  const t = useTranslations("participants");
  const tn = useTranslations("common.nouns");
  const rel = useRelativeTime();
  const participants = useParticipants(competitionId);
  const selfId = useAuthStore((s) => s.user?.id);
  const access = useAccess();
  const canAward = access.has("score_override");
  const [awardOpen, setAwardOpen] = useState(false);

  // Sort / search / pagination over the fetched roster (#16 #17 #20). Declared
  // before the early returns below — hooks must run unconditionally.
  const roster = participants.data ?? [];
  const table = useDataTable(roster, {
    columns: {
      rank: (p: Participant) => p.rank,
      name: (p: Participant) => p.display_name,
      solves: { value: (p: Participant) => p.solve_count, defaultDir: "desc" },
      points: { value: (p: Participant) => p.points, defaultDir: "desc" },
      joined: (p: Participant) => p.joined_at,
    },
    searchKeys: [(p: Participant) => p.display_name],
  });
  const dir = (key: string) => (table.sort?.key === key ? table.sort.dir : null);

  if (participants.isLoading) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (roster.length === 0) {
    return (
      <EmptyState
        icon={<PeopleEmptyIcon />}
        title={t("empty.title")}
        description={t("empty.description")}
      />
    );
  }

  const me = roster.find((p) => p.user_id === selfId) ?? null;

  return (
    <div className="space-y-6">
      {me && <YouCard participant={me} total={roster.length} />}

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-2">
          <div>
            <CardTitle>{t("roster.title")}</CardTitle>
            <CardDescription>{t("roster.count", { count: roster.length })}</CardDescription>
          </div>
          {canAward && (
            <Button size="sm" onClick={() => setAwardOpen(true)}>
              {t("roster.createAward")}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          <TableSearchInput
            value={table.query}
            onChange={table.setQuery}
            placeholder={t("roster.searchPlaceholder")}
            className="mb-4"
          />
          <Table>
            <TableHeader>
              <TableRow>
                <SortableTableHead align="right" active={dir("rank")} onSort={() => table.toggleSort("rank")}>
                  {t("roster.colRank")}
                </SortableTableHead>
                <SortableTableHead active={dir("name")} onSort={() => table.toggleSort("name")}>
                  {t("roster.colCompetitor")}
                </SortableTableHead>
                <SortableTableHead align="right" active={dir("solves")} onSort={() => table.toggleSort("solves")}>
                  {t("roster.colSolves")}
                </SortableTableHead>
                <SortableTableHead align="right" active={dir("points")} onSort={() => table.toggleSort("points")}>
                  {t("roster.colPoints")}
                </SortableTableHead>
                <SortableTableHead align="right" active={dir("joined")} onSort={() => table.toggleSort("joined")}>
                  {t("roster.colJoined")}
                </SortableTableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {table.rows.map((p) => (
                <TableRow
                  key={p.user_id}
                  className={cn(p.user_id === selfId && "bg-primary/5")}
                >
                  <TableCell className="text-right font-mono text-muted-foreground">
                    {p.rank ?? "—"}
                  </TableCell>
                  <TableCell className="font-medium">
                    {p.display_name}
                    {p.user_id === selfId && (
                      <span className="ml-2 text-xs text-primary">{t("roster.you")}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right font-mono">{p.solve_count}</TableCell>
                  <TableCell className="text-right font-mono">{p.points}</TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    {rel(p.joined_at)}
                  </TableCell>
                </TableRow>
              ))}
              {table.rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground">
                    {t("roster.noMatch")}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          <TablePagination table={table} noun={tn("competitors")} className="mt-4" />
        </CardContent>
      </Card>

      {canAward && (
        <AwardDialog
          key={awardOpen ? "open" : "closed"}
          competitionId={competitionId}
          roster={roster}
          open={awardOpen}
          onOpenChange={setAwardOpen}
        />
      )}
    </div>
  );
}

function YouCard({ participant, total }: { participant: Participant; total: number }) {
  const t = useTranslations("participants.you");
  const stats = [
    {
      label: t("rankLabel"),
      value: participant.rank ? t("rankValue", { rank: participant.rank, total }) : "—",
    },
    { label: t("pointsLabel"), value: participant.points },
    { label: t("solvesLabel"), value: participant.solve_count },
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>{participant.display_name}</CardTitle>
        <CardDescription>{t("subtitle")}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-4">
          {stats.map((s) => (
            <div key={s.label}>
              <div className="text-2xl font-semibold tabular-nums">{s.value}</div>
              <div className="text-xs text-muted-foreground">{s.label}</div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
