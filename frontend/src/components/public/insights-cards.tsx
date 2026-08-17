"use client";

import { useTranslations } from "next-intl";

import { Card, CardContent } from "@/components/ui/card";
import type { PublicInsights } from "@/lib/types";

// Shared spectator insight cards (#24), extracted from the public page so the
// static spectator view and venue mode (#77) render them from one source
// instead of forking. Pure presentation — the caller owns the data fetch.

/** Headline counts, in the same compact card idiom as the analytics overview. */
export function StatTiles({ stats }: { stats: PublicInsights["stats"] }) {
  const t = useTranslations("scoreboard.public.insights");
  const tiles = [
    { label: t("participants"), value: stats.participants },
    { label: t("solves"), value: stats.solves },
    { label: t("challenges"), value: stats.challenges },
    { label: t("unsolved"), value: stats.unsolved },
  ];
  return (
    <div className="grid grid-cols-2 gap-[1em] md:grid-cols-4">
      {tiles.map((tile) => (
        <Card key={tile.label}>
          <CardContent className="p-[1em]">
            <div className="text-[1.5em] font-semibold tabular-nums">{tile.value}</div>
            <div className="text-[0.75em] text-muted-foreground">{tile.label}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function Highlights({
  highlights,
  variant = "column",
}: {
  highlights: PublicInsights["highlights"];
  // "column" stacks beside the static standings table; "row" spreads across a
  // full-width venue slide (#77).
  variant?: "column" | "row";
}) {
  const t = useTranslations("scoreboard.public.insights");
  const { most_solved, most_attempted, first_blood_leader, fastest_solve } =
    highlights;
  const cards = [
    most_solved && {
      label: t("mostSolved"),
      value: most_solved.title,
      detail: t("mostSolvedDetail", { count: most_solved.count }),
    },
    most_attempted && {
      label: t("mostAttempted"),
      value: most_attempted.title,
      detail: t("mostAttemptedDetail", { count: most_attempted.count }),
    },
    first_blood_leader && {
      label: t("mostFirstBloods"),
      value: first_blood_leader.name,
      detail: t("mostFirstBloodsDetail", { count: first_blood_leader.count }),
    },
    fastest_solve && {
      label: t("fastestSolve"),
      value: fastest_solve.title,
      detail: t("fastestSolveDetail", {
        name: fastest_solve.name,
        elapsed: formatElapsed(fastest_solve.seconds),
      }),
    },
  ].filter(Boolean) as { label: string; value: string; detail: string }[];

  if (cards.length === 0) return null;

  // Column (default): self-start keeps the cards their natural height beside the
  // standings table, where stretching would inflate each to the table's height.
  // Row: spread evenly across a full-width venue slide.
  const grid =
    variant === "row"
      ? "grid gap-[1em] sm:grid-cols-2 lg:grid-cols-4"
      : "grid gap-[1em] self-start sm:grid-cols-2 lg:grid-cols-1";
  return (
    <div className={grid}>
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="p-[1em]">
            <div className="text-[0.75em] text-muted-foreground">{card.label}</div>
            <div className="mt-[0.125em] truncate font-medium" title={card.value}>
              {card.value}
            </div>
            <div className="text-[0.75em] text-muted-foreground">{card.detail}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/** Time from the competition start, in the coarsest useful unit. */
export function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}
