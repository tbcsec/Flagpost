"use client";

import Link from "next/link";
import { use } from "react";

import { PoweredByFooter } from "@/components/app/powered-by-footer";
import { Lockup } from "@/components/brand/flagpost-mark";
import { PointsTimeline } from "@/components/public/points-timeline";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { FALLBACK_SETTINGS, useSiteSettings } from "@/lib/hooks/use-site-settings";
import {
  usePublicInsights,
  usePublicScoreboard,
} from "@/lib/hooks/use-public-scoreboard";
import type { PublicInsights } from "@/lib/types";

// The standalone spectator scoreboard (no login) for a public competition.
// Lives outside the (app) shell so it needs no account; brand comes from the
// public site settings, attribution from the mandatory footer. Wider than the
// app's own pages (#24) because the points timeline wants the room.
export default function PublicScoreboardPage({
  params,
}: {
  params: Promise<{ competitionId: string }>;
}) {
  const { competitionId } = use(params);
  const { data, isLoading, isError } = usePublicScoreboard(competitionId);
  // Insights are a separate fetch: richer, and if it fails the standings — the
  // thing people came for — still render.
  const { data: insights } = usePublicInsights(competitionId);
  const { data: settings } = useSiteSettings();
  const brand = settings ?? FALLBACK_SETTINGS;

  return (
    <div className="mx-auto flex min-h-dvh max-w-7xl flex-col gap-6 px-4 py-8">
      <header className="flex items-center justify-between gap-3">
        <Lockup
          size={32}
          label={brand.platform_name}
          logoUrl={brand.logo_url}
          showWordmark={brand.show_wordmark}
        />
        {data?.frozen && <Badge variant="secondary">Frozen</Badge>}
      </header>

      {isLoading && <Skeleton className="h-64 w-full" />}
      {isError && (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            This scoreboard isn&apos;t public, or the competition doesn&apos;t exist.
          </CardContent>
        </Card>
      )}

      {data && (
        <>
          <div>
            <Link href="/public" className="text-xs text-primary underline">
              ← All public scoreboards
            </Link>
            <h1 className="mt-1 text-2xl font-semibold">{data.name}</h1>
            <p className="text-sm text-muted-foreground">
              {data.mode === "team" ? "Team" : "Individual"} scoreboard
              {data.frozen && " · frozen"}
            </p>
          </div>

          {insights && <StatTiles stats={insights.stats} />}

          {insights && (
            <PointsTimeline
              series={insights.timeline.series}
              start={insights.timeline.start}
              end={insights.timeline.end}
              frozen={insights.frozen}
            />
          )}

          {data.entries.length === 0 ? (
            <Card>
              <CardContent className="p-8 text-center text-sm text-muted-foreground">
                No scores yet — the board fills in on the first solve.
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 lg:grid-cols-3">
              <Card className="lg:col-span-2">
                <CardContent className="pt-2">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-12">Rank</TableHead>
                        <TableHead>
                          {data.mode === "team" ? "Team" : "Competitor"}
                        </TableHead>
                        <TableHead className="text-right">Points</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.entries.map((e) => (
                        <TableRow key={e.subject_id}>
                          <TableCell className="font-mono text-muted-foreground">
                            {e.rank}
                          </TableCell>
                          <TableCell className="font-medium">{e.name}</TableCell>
                          <TableCell className="text-right font-mono">
                            {e.points}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>

              {insights && <Highlights highlights={insights.highlights} />}
            </div>
          )}
        </>
      )}

      <PoweredByFooter className="mt-auto" />
    </div>
  );
}

/** Headline counts, in the same compact card idiom as the analytics overview. */
function StatTiles({ stats }: { stats: PublicInsights["stats"] }) {
  const tiles = [
    { label: "Participants", value: stats.participants },
    { label: "Solves", value: stats.solves },
    { label: "Challenges", value: stats.challenges },
    { label: "Unsolved", value: stats.unsolved },
  ];
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      {tiles.map((tile) => (
        <Card key={tile.label}>
          <CardContent className="p-4">
            <div className="text-2xl font-semibold tabular-nums">{tile.value}</div>
            <div className="text-xs text-muted-foreground">{tile.label}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function Highlights({
  highlights,
}: {
  highlights: PublicInsights["highlights"];
}) {
  const { most_solved, most_attempted, first_blood_leader, fastest_solve } =
    highlights;
  const cards = [
    most_solved && {
      label: "Most solved",
      value: most_solved.title,
      detail: `${most_solved.count} ${most_solved.count === 1 ? "solve" : "solves"}`,
    },
    most_attempted && {
      label: "Most attempted",
      value: most_attempted.title,
      detail: `${most_attempted.count} attempts`,
    },
    first_blood_leader && {
      label: "Most first bloods",
      value: first_blood_leader.name,
      detail: `${first_blood_leader.count} first ${
        first_blood_leader.count === 1 ? "blood" : "bloods"
      }`,
    },
    fastest_solve && {
      label: "Fastest solve",
      value: fastest_solve.title,
      detail: `${fastest_solve.name} · ${formatElapsed(fastest_solve.seconds)}`,
    },
  ].filter(Boolean) as { label: string; value: string; detail: string }[];

  if (cards.length === 0) return null;

  // self-start keeps the cards their natural height: beside the standings table
  // the grid row is as tall as the table, and stretching would inflate each
  // card to fill it.
  return (
    <div className="grid gap-4 self-start sm:grid-cols-2 lg:grid-cols-1">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="p-4">
            <div className="text-xs text-muted-foreground">{card.label}</div>
            <div className="mt-0.5 truncate font-medium" title={card.value}>
              {card.value}
            </div>
            <div className="text-xs text-muted-foreground">{card.detail}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/** Time from the competition start, in the coarsest useful unit. */
function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}
