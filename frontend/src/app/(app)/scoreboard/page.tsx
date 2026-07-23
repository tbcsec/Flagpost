"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { NoCompetition } from "@/components/app/no-competition";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, TrophyEmptyIcon } from "@/components/ui/empty-state";
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
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useMyTeam } from "@/lib/hooks/use-teams";
import { useScoreboard } from "@/lib/hooks/use-scoreboard";
import { useAuthStore } from "@/stores/auth";
import { cn } from "@/lib/utils";

// Live scoreboard (Phase 7): REST initial load + WebSocket room updates. "You"
// highlighting follows the scoring subject; the top three get a medal rank and
// rows flash briefly when their points change on a live update.
function RankBadge({ rank }: { rank: number }) {
  if (rank > 3) return <span className="font-mono text-muted-foreground">{rank}</span>;
  const style = {
    1: "bg-warning text-warning-foreground",
    2: "bg-secondary text-secondary-foreground",
    3: "bg-muted text-muted-foreground",
  }[rank as 1 | 2 | 3];
  return (
    <span
      className={cn(
        "inline-flex h-6 w-6 items-center justify-center rounded-full font-mono text-xs font-semibold",
        style,
      )}
    >
      {rank}
    </span>
  );
}

export default function ScoreboardPage() {
  const { competitionId, data: competition } = useActiveCompetition();
  const board = useScoreboard(competitionId ?? "");
  const isTeam = competition?.participation_mode !== "individual";
  const myTeam = useMyTeam(isTeam ? (competitionId ?? "") : "");
  const userId = useAuthStore((s) => s.user?.id);

  // Memoised so the flash-detection effect below only re-runs when the board
  // data actually changes, not on every render (the `?? []` would otherwise be
  // a fresh array reference each time).
  const entries = useMemo(() => board.data?.entries ?? [], [board.data?.entries]);

  // Flash a row whose points changed since the last live update. A colour
  // transition (not a looping pulse) fades the highlight out on its own.
  const prevPoints = useRef<Record<string, number>>({});
  const [flashing, setFlashing] = useState<Set<string>>(new Set());
  useEffect(() => {
    const changed: string[] = [];
    for (const e of entries) {
      const prev = prevPoints.current[e.subject_id];
      if (prev !== undefined && prev !== e.points) changed.push(e.subject_id);
      prevPoints.current[e.subject_id] = e.points;
    }
    if (changed.length === 0) return;
    setFlashing(new Set(changed));
    const t = setTimeout(() => setFlashing(new Set()), 1200);
    return () => clearTimeout(t);
  }, [entries]);

  if (!competitionId) {
    return <NoCompetition />;
  }

  const mySubjectId = isTeam ? myTeam.data?.id : userId;
  const top = entries.slice(0, 10);
  const maxPoints = Math.max(1, ...top.map((e) => e.points));
  const live = board.socketStatus === "open";

  return (
    <>
      <SectionHeader
        title="Scoreboard"
        subtitle={
          <>
            {competition?.name ?? ""} · {isTeam ? "team" : "individual"} mode
            {live && (
              <span className="ml-2 inline-flex items-center gap-1.5 text-primary">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                live
              </span>
            )}
          </>
        }
      />

      {board.isLoading && (
        <div className="grid gap-4">
          <Skeleton className="h-44 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      )}
      {board.isError && (
        <p className="text-sm text-destructive">{(board.error as Error).message}</p>
      )}

      {board.data && entries.length === 0 && (
        <EmptyState
          icon={<TrophyEmptyIcon />}
          title="No scores yet"
          description={`The board fills in the moment ${
            isTeam ? "a team" : "someone"
          } lands a solve. First flag takes the top spot.`}
        />
      )}

      {top.length > 0 && (
        <Card>
          <CardContent className="pt-5">
            <div className="flex h-40 items-end gap-2.5">
              {top.map((e) => (
                <div
                  key={e.subject_id}
                  className="flex h-full flex-1 flex-col items-center justify-end gap-1.5"
                >
                  <div
                    className={cn(
                      "w-full rounded-t transition-[height] duration-500",
                      e.subject_id === mySubjectId ? "bg-primary" : "bg-secondary",
                    )}
                    style={{ height: `${Math.round((e.points / maxPoints) * 100)}%` }}
                  />
                  <span className="max-w-full truncate text-[10px] text-muted-foreground">
                    {e.rank}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {entries.length > 0 && (
        <Card>
          <CardContent className="pt-2">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Rank</TableHead>
                  <TableHead>{isTeam ? "Team" : "Participant"}</TableHead>
                  <TableHead>Points</TableHead>
                  <TableHead>Last solve</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((e) => (
                  <TableRow
                    key={e.subject_id}
                    className={cn(
                      "transition-colors duration-700",
                      flashing.has(e.subject_id) && "bg-success/15",
                      e.subject_id === mySubjectId && "bg-primary/10",
                    )}
                  >
                    <TableCell>
                      <RankBadge rank={e.rank} />
                    </TableCell>
                    <TableCell className="font-medium">
                      {e.name}
                      {e.subject_id === mySubjectId && (
                        <span className="ml-2 text-[11px] text-primary">you</span>
                      )}
                    </TableCell>
                    <TableCell className="font-mono">{e.points}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {e.last_solve_at
                        ? parseServerDate(e.last_solve_at).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </>
  );
}
