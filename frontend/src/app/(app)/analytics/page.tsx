"use client";

import * as React from "react";

import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { relativeTime } from "@/lib/datetime";
import { useChallengeAnalytics, useTeamAnalytics } from "@/lib/hooks/use-analytics";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useAccess } from "@/lib/hooks/use-permissions";
import type { ChallengeAnalyticsReport } from "@/lib/types";

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
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Challenge</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead className="text-right">Points</TableHead>
                    <TableHead className="text-right">Solves</TableHead>
                    <TableHead className="text-right">Completion</TableHead>
                    <TableHead className="text-right">Avg. time</TableHead>
                    <TableHead className="text-right">Attempts</TableHead>
                    <TableHead className="text-right">Hints</TableHead>
                    <TableHead className="text-right">Tickets</TableHead>
                    <TableHead className="text-right">Rating</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {challenges.data.challenges.map((c) => (
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
                  {challenges.data.challenges.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={9} className="text-center text-muted-foreground">
                        No challenges yet.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{challenges.data.mode === "team" ? "Teams" : "Competitors"}</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-right">#</TableHead>
                    <TableHead>{challenges.data.mode === "team" ? "Team" : "Competitor"}</TableHead>
                    <TableHead className="text-right">Points</TableHead>
                    <TableHead className="text-right">Solves</TableHead>
                    <TableHead className="text-right">First bloods</TableHead>
                    <TableHead className="text-right">Tickets</TableHead>
                    <TableHead className="text-right">Last solve</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(teams.data?.teams ?? []).map((t) => (
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
                  {teams.data && teams.data.teams.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center text-muted-foreground">
                        No participants yet.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}
    </>
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
