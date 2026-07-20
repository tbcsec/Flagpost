"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { SCOREBOARD } from "@/lib/placeholder-data";
import { cn } from "@/lib/utils";

// Scoreboard. The real thing is Tier 1 Phase 7 (scoring computation + the
// WebSocket live-update layer); until then this renders the design against
// placeholder rows. The name column DOES reflect the active competition's real
// participation mode.
export default function ScoreboardPage() {
  const { data: competition } = useActiveCompetition();
  const isTeam = competition?.participation_mode !== "individual";
  const nameCol = isTeam ? "Team" : "Participant";
  const max = Math.max(...SCOREBOARD.map((r) => r.points));

  return (
    <>
      <SectionHeader
        title="Scoreboard"
        subtitle={`${competition?.name ?? ""} · ${isTeam ? "team" : "individual"} mode · top 10 by points`}
      />

      <NotWiredNote>
        Scoring and the live-updating scoreboard are Tier&nbsp;1 Phase&nbsp;7.
        Rankings shown are placeholder.
      </NotWiredNote>

      <Card>
        <CardContent className="pt-5">
          <div className="flex h-40 items-end gap-2.5">
            {SCOREBOARD.map((t, i) => (
              <div key={t.id} className="flex h-full flex-1 flex-col items-center justify-end gap-1.5">
                <div
                  className={cn("w-full rounded-t", t.mine ? "bg-primary" : "bg-secondary")}
                  style={{ height: `${Math.round((t.points / max) * 100)}%` }}
                />
                <span className="max-w-full truncate text-[10px] text-muted-foreground">{i + 1}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-2">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Rank</TableHead>
                <TableHead>{nameCol}</TableHead>
                <TableHead>Points</TableHead>
                <TableHead>Last solve</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {SCOREBOARD.map((row, i) => (
                <TableRow key={row.id} className={cn(row.mine && "bg-primary/10")}>
                  <TableCell className="font-mono text-muted-foreground">{i + 1}</TableCell>
                  <TableCell className="font-medium">
                    {row.name}
                    {row.mine && <span className="ml-2 text-[11px] text-primary">you</span>}
                  </TableCell>
                  <TableCell className="font-mono">{row.points}</TableCell>
                  <TableCell className="text-muted-foreground">{row.lastSolve}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}
