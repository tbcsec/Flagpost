"use client";

import * as React from "react";

import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  SortableTableHead,
  TablePagination,
  TableSearchInput,
} from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { relativeTime } from "@/lib/datetime";
import { useChallengeAnalytics, useTeamAnalytics } from "@/lib/hooks/use-analytics";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useDataTable, type DataTableState } from "@/lib/hooks/use-data-table";
import { useAccess } from "@/lib/hooks/use-permissions";
import type {
  ChallengeAnalytics,
  ChallengeAnalyticsReport,
  TeamAnalytics,
} from "@/lib/types";

// Challenge & team analytics (ROADMAP #23) — read-only reporting off the
// submissions / hints / tickets data scoring already records. Staff-gated
// (view_competition_analytics); the `analytics` optional module can be disabled.
export default function AnalyticsPage() {
  const { data: competition } = useActiveCompetition();
  const access = useAccess();
  const canView = access.has("view_competition_analytics");
  const enabled = Boolean(competition) && canView;

  const challenges = useChallengeAnalytics(competition?.id ?? "", enabled);
  const teams = useTeamAnalytics(competition?.id ?? "", enabled);

  // Sort / search / pagination (#16 #17 #20) — two independent instances, one
  // per table, derived off the fetched reports.
  const challengeTable = useDataTable(challenges.data?.challenges ?? [], {
    columns: {
      title: (c: ChallengeAnalytics) => c.title,
      category: (c: ChallengeAnalytics) => c.category,
      points: { value: (c: ChallengeAnalytics) => c.points, defaultDir: "desc" },
      solves: { value: (c: ChallengeAnalytics) => c.solve_count, defaultDir: "desc" },
      completion: { value: (c: ChallengeAnalytics) => c.completion_rate, defaultDir: "desc" },
      avg_time: (c: ChallengeAnalytics) => c.avg_solve_time_seconds,
      attempts: { value: (c: ChallengeAnalytics) => c.attempt_count, defaultDir: "desc" },
      hints: { value: (c: ChallengeAnalytics) => c.hints_used, defaultDir: "desc" },
      tickets: { value: (c: ChallengeAnalytics) => c.ticket_count, defaultDir: "desc" },
      rating: { value: (c: ChallengeAnalytics) => c.avg_rating, defaultDir: "desc" },
    },
    searchKeys: [(c: ChallengeAnalytics) => c.title],
  });
  const teamTable = useDataTable(teams.data?.teams ?? [], {
    columns: {
      rank: (t: TeamAnalytics) => t.rank,
      name: (t: TeamAnalytics) => t.name,
      points: { value: (t: TeamAnalytics) => t.points, defaultDir: "desc" },
      solves: { value: (t: TeamAnalytics) => t.solve_count, defaultDir: "desc" },
      first_bloods: { value: (t: TeamAnalytics) => t.first_bloods, defaultDir: "desc" },
      tickets: { value: (t: TeamAnalytics) => t.ticket_count, defaultDir: "desc" },
      last_solve: { value: (t: TeamAnalytics) => t.last_solve_at, defaultDir: "desc" },
    },
    searchKeys: [(t: TeamAnalytics) => t.name],
  });

  return (
    <>
      <SectionHeader
        title="Analytics"
        subtitle={`${competition?.name ?? ""} · read-only reporting`}
      />

      {!access.ready ? (
        <Skeleton className="h-24" />
      ) : !canView ? (
        <EmptyCard>You don&apos;t have access to this competition&apos;s analytics.</EmptyCard>
      ) : challenges.isError ? (
        <EmptyCard>The analytics module is disabled for this competition.</EmptyCard>
      ) : challenges.isLoading || !challenges.data ? (
        <div className="grid gap-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-64" />
        </div>
      ) : (
        <div className="grid gap-6">
          <Overview report={challenges.data} />

          <Card>
            <CardHeader>
              <CardTitle>Per-challenge</CardTitle>
            </CardHeader>
            <CardContent>
              <TableSearchInput
                value={challengeTable.query}
                onChange={challengeTable.setQuery}
                placeholder="Search challenges…"
                className="mb-4"
              />
              <Table>
                <TableHeader>
                  <TableRow>
                    <Sortable table={challengeTable} k="title">Challenge</Sortable>
                    <Sortable table={challengeTable} k="category">Category</Sortable>
                    <Sortable table={challengeTable} k="points" right>Points</Sortable>
                    <Sortable table={challengeTable} k="solves" right>Solves</Sortable>
                    <Sortable table={challengeTable} k="completion" right>Completion</Sortable>
                    <Sortable table={challengeTable} k="avg_time" right>Avg. time</Sortable>
                    <Sortable table={challengeTable} k="attempts" right>Attempts</Sortable>
                    <Sortable table={challengeTable} k="hints" right>Hints</Sortable>
                    <Sortable table={challengeTable} k="tickets" right>Tickets</Sortable>
                    <Sortable table={challengeTable} k="rating" right>Rating</Sortable>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {challengeTable.rows.map((c) => (
                    <TableRow key={c.challenge_id}>
                      <TableCell className="font-medium">
                        {c.title}
                        {c.state !== "published" && (
                          <Badge variant="muted" className="ml-2">
                            {c.state}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {c.category ?? "—"}
                      </TableCell>
                      <TableCell className="text-right font-mono">{c.points}</TableCell>
                      <TableCell className="text-right font-mono">{c.solve_count}</TableCell>
                      <TableCell className="text-right font-mono">
                        {formatPercent(c.completion_rate)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatDuration(c.avg_solve_time_seconds)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {c.attempt_count}
                        {c.fail_count > 0 && (
                          <span className="text-muted-foreground"> ({c.fail_count} failed)</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono">{c.hints_used}</TableCell>
                      <TableCell className="text-right font-mono">{c.ticket_count}</TableCell>
                      <TableCell className="text-right font-mono">
                        {c.avg_rating != null ? (
                          <>
                            <span className="text-primary">★</span> {c.avg_rating.toFixed(1)}
                            <span className="text-muted-foreground"> ({c.rating_count})</span>
                          </>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                  {challengeTable.rows.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={10} className="text-center text-muted-foreground">
                        {challengeTable.query
                          ? "No challenges match your search."
                          : "No challenges yet."}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
              <TablePagination table={challengeTable} noun="challenges" className="mt-4" />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{challenges.data.mode === "team" ? "Teams" : "Competitors"}</CardTitle>
            </CardHeader>
            <CardContent>
              <TableSearchInput
                value={teamTable.query}
                onChange={teamTable.setQuery}
                placeholder={
                  challenges.data.mode === "team" ? "Search teams…" : "Search competitors…"
                }
                className="mb-4"
              />
              <Table>
                <TableHeader>
                  <TableRow>
                    <Sortable table={teamTable} k="rank" right>#</Sortable>
                    <Sortable table={teamTable} k="name">
                      {challenges.data.mode === "team" ? "Team" : "Competitor"}
                    </Sortable>
                    <Sortable table={teamTable} k="points" right>Points</Sortable>
                    <Sortable table={teamTable} k="solves" right>Solves</Sortable>
                    <Sortable table={teamTable} k="first_bloods" right>First bloods</Sortable>
                    <Sortable table={teamTable} k="tickets" right>Tickets</Sortable>
                    <Sortable table={teamTable} k="last_solve" right>Last solve</Sortable>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {teamTable.rows.map((t) => (
                    <TableRow key={t.subject_id}>
                      <TableCell className="text-right font-mono text-muted-foreground">
                        {t.rank}
                      </TableCell>
                      <TableCell className="font-medium">{t.name}</TableCell>
                      <TableCell className="text-right font-mono">{t.points}</TableCell>
                      <TableCell className="text-right font-mono">{t.solve_count}</TableCell>
                      <TableCell className="text-right font-mono">
                        {t.first_bloods > 0 ? (
                          <span className="text-success">{t.first_bloods}</span>
                        ) : (
                          t.first_bloods
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono">{t.ticket_count}</TableCell>
                      <TableCell className="text-right text-muted-foreground">
                        {t.last_solve_at ? relativeTime(t.last_solve_at) : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                  {teams.data && teamTable.rows.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center text-muted-foreground">
                        {teamTable.query
                          ? "Nobody matches your search."
                          : "No participants yet."}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
              <TablePagination
                table={teamTable}
                noun={challenges.data.mode === "team" ? "teams" : "competitors"}
                className="mt-4"
              />
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}

/** Local shorthand — wires a SortableTableHead to a useDataTable instance so
 *  the header rows above stay readable with ten columns. */
function Sortable<T>({
  table,
  k,
  right,
  children,
}: {
  table: DataTableState<T>;
  k: string;
  right?: boolean;
  children: React.ReactNode;
}) {
  return (
    <SortableTableHead
      align={right ? "right" : "left"}
      active={table.sort?.key === k ? table.sort.dir : null}
      onSort={() => table.toggleSort(k)}
    >
      {children}
    </SortableTableHead>
  );
}

function Overview({ report }: { report: ChallengeAnalyticsReport }) {
  const totalSolves = report.challenges.reduce((n, c) => n + c.solve_count, 0);
  const totalAttempts = report.challenges.reduce((n, c) => n + c.attempt_count, 0);
  const stats = [
    { label: report.mode === "team" ? "Teams" : "Competitors", value: report.subject_count },
    { label: "Challenges", value: report.challenges.length },
    { label: "Total solves", value: totalSolves },
    { label: "Total attempts", value: totalAttempts },
  ];
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      {stats.map((s) => (
        <Card key={s.label}>
          <CardContent className="p-4">
            <div className="text-2xl font-semibold tabular-nums">{s.value}</div>
            <div className="text-xs text-muted-foreground">{s.label}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function EmptyCard({ children }: { children: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="p-10 text-center">
        <p className="text-sm text-muted-foreground">{children}</p>
      </CardContent>
    </Card>
  );
}

function formatPercent(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const totalMinutes = Math.floor(seconds / 60);
  if (totalMinutes >= 60) {
    const h = Math.floor(totalMinutes / 60);
    return `${h}h ${totalMinutes % 60}m`;
  }
  if (totalMinutes > 0) return `${totalMinutes}m`;
  return `${Math.round(seconds)}s`;
}
