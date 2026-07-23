"use client";

// Individual-mode participant roster (§14 components/<domain>). The counterpart
// to TeamPanel for competitions without teams: a compact "you" summary plus the
// full roster with standing, all via the use-participants hook. Server state
// only; no client-side ranking (the backend reuses the scoreboard computation).

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { EmptyState, PeopleEmptyIcon } from "@/components/ui/empty-state";
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
import { useParticipants } from "@/lib/hooks/use-participants";
import type { Participant } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";

export function ParticipantsPanel({ competitionId }: { competitionId: string }) {
  const participants = useParticipants(competitionId);
  const selfId = useAuthStore((s) => s.user?.id);

  if (participants.isLoading) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const roster = participants.data ?? [];
  if (roster.length === 0) {
    return (
      <EmptyState
        icon={<PeopleEmptyIcon />}
        title="No competitors yet"
        description="Registered competitors show up here as they join — share the join link to get people in."
      />
    );
  }

  const me = roster.find((p) => p.user_id === selfId) ?? null;

  return (
    <div className="space-y-6">
      {me && <YouCard participant={me} total={roster.length} />}

      <Card>
        <CardHeader>
          <CardTitle>Competitors</CardTitle>
          <CardDescription>{roster.length} registered</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-right">#</TableHead>
                <TableHead>Competitor</TableHead>
                <TableHead className="text-right">Solves</TableHead>
                <TableHead className="text-right">Points</TableHead>
                <TableHead className="text-right">Joined</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {roster.map((p) => (
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
                      <span className="ml-2 text-xs text-primary">You</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right font-mono">{p.solve_count}</TableCell>
                  <TableCell className="text-right font-mono">{p.points}</TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    {relativeTime(p.joined_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function YouCard({ participant, total }: { participant: Participant; total: number }) {
  const stats = [
    { label: "Rank", value: participant.rank ? `${participant.rank} of ${total}` : "—" },
    { label: "Points", value: participant.points },
    { label: "Solves", value: participant.solve_count },
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>{participant.display_name}</CardTitle>
        <CardDescription>Your standing in this competition</CardDescription>
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
