"use client";

import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { useAdminOverview } from "@/lib/hooks/use-admin-overview";
import { useAccess } from "@/lib/hooks/use-permissions";
import type { AdminOverview, CompetitionHealth } from "@/lib/types";

// Admin → Dashboard. The site-wide overview (§6.3) — platform totals + every
// competition's status and health for a global Administrator. Reads the
// cross-competition /api/admin/overview, gated on view_global_analytics.
export default function AdminDashboardPage() {
  const access = useAccess();
  const canView = access.has("view_global_analytics");
  const overview = useAdminOverview(canView);

  return (
    <>
      <SectionHeader title="Admin — Dashboard" subtitle="Global — status & health across every competition" />

      {!access.ready ? (
        <Skeleton className="h-24 w-full" />
      ) : !canView ? (
        <EmptyState title="No access" description="You need the view-global-analytics permission to see the platform overview." />
      ) : overview.isLoading || !overview.data ? (
        <div className="grid gap-4">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : (
        <div className="grid gap-6">
          <Totals data={overview.data} />

          <Card>
            <CardHeader>
              <CardTitle>Competitions</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Mode</TableHead>
                    <TableHead>Visibility</TableHead>
                    <TableHead className="text-right">Participants</TableHead>
                    <TableHead className="text-right">Challenges</TableHead>
                    <TableHead className="text-right">Solves</TableHead>
                    <TableHead className="text-right">Open tickets</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {overview.data.competitions.map((c) => (
                    <TableRow key={c.id} className={c.status === "archived" ? "opacity-60" : undefined}>
                      <TableCell className="font-medium">{c.name}</TableCell>
                      <TableCell>
                        <StatusBadge status={c.status} />
                      </TableCell>
                      <TableCell className="capitalize text-muted-foreground">{c.participation_mode}</TableCell>
                      <TableCell className="capitalize text-muted-foreground">{c.visibility}</TableCell>
                      <TableCell className="text-right font-mono">{c.participants}</TableCell>
                      <TableCell className="text-right font-mono">{c.published_challenges}</TableCell>
                      <TableCell className="text-right font-mono">{c.solves}</TableCell>
                      <TableCell className="text-right font-mono">
                        {c.open_tickets > 0 ? (
                          <span className="text-warning">{c.open_tickets}</span>
                        ) : (
                          c.open_tickets
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                  {overview.data.competitions.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={8} className="text-center text-muted-foreground">
                        No competitions yet.
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

function Totals({ data }: { data: AdminOverview }) {
  const tiles = [
    { label: "Competitions", value: data.active_competitions, sub: `${data.archived_competitions} archived` },
    { label: "Accounts", value: data.active_users, sub: `${data.total_users - data.active_users} banned` },
    { label: "Teams", value: data.total_teams },
    { label: "Challenges", value: data.published_challenges, sub: `${data.total_challenges} total` },
    { label: "Solves", value: data.total_solves },
    { label: "Submissions", value: data.total_submissions },
  ];
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
      {tiles.map((t) => (
        <Card key={t.label}>
          <CardContent className="p-4">
            <div className="font-display text-2xl font-semibold tabular-nums">{t.value}</div>
            <div className="text-xs text-muted-foreground">{t.label}</div>
            {t.sub && <div className="mt-0.5 text-[11px] text-muted-foreground/70">{t.sub}</div>}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

const STATUS_VARIANT: Record<CompetitionHealth["status"], "success" | "secondary" | "muted" | "outline"> = {
  running: "success",
  scheduled: "secondary",
  ended: "muted",
  archived: "outline",
  draft: "outline",
};

function StatusBadge({ status }: { status: CompetitionHealth["status"] }) {
  return <Badge variant={STATUS_VARIANT[status]} className="capitalize">{status}</Badge>;
}
