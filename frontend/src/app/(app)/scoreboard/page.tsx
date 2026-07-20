"use client";

import { SectionHeader } from "@/components/app/section-header";
import { Card, CardContent } from "@/components/ui/card";
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
// highlighting follows the scoring subject — your team in team-mode, your own
// account in individual-mode.
export default function ScoreboardPage() {
  const { competitionId, data: competition } = useActiveCompetition();
  const board = useScoreboard(competitionId ?? "");
  const isTeam = competition?.participation_mode !== "individual";
  const myTeam = useMyTeam(isTeam ? (competitionId ?? "") : "");
  const userId = useAuthStore((s) => s.user?.id);

  if (!competitionId) {
    return <p className="text-sm text-muted-foreground">No competition selected.</p>;
  }

  const mySubjectId = isTeam ? myTeam.data?.id : userId;
  const entries = board.data?.entries ?? [];
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
        <p className="text-sm text-muted-foreground">Loading scoreboard…</p>
      )}
      {board.isError && (
        <p className="text-sm text-destructive">{(board.error as Error).message}</p>
      )}

      {board.data && entries.length === 0 && (
        <Card>
          <CardContent className="p-10 text-center">
            <p className="text-sm text-muted-foreground">
              No {isTeam ? "teams" : "participants"} yet — the board fills in as
              people join.
            </p>
          </CardContent>
        </Card>
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
                      "w-full rounded-t",
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
                    className={cn(e.subject_id === mySubjectId && "bg-primary/10")}
                  >
                    <TableCell className="font-mono text-muted-foreground">{e.rank}</TableCell>
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
