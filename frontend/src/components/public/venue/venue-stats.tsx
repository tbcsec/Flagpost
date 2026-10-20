"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { formatElapsed } from "@/components/public/insights-cards";
import { CLIMB_WINDOW_MS } from "@/components/public/venue/venue-timeline";
import { useBoxSize, useFitCount, useHeights } from "@/components/public/venue/use-fit";
import { FirstBloodIcon } from "@/components/ui/first-blood-icon";
import { parseServerDate } from "@/lib/datetime";
import type { PublicActivity, PublicInsights, PublicScoreboard } from "@/lib/types";
import { cn } from "@/lib/utils";
import { biggestRankClimb, closestRace, fitCount, hotStreak, timelineEnd } from "@/lib/venue-race";

// The venue stats slide (#513): a live solve ticker down the left — the feed
// already polled for the first-blood splash, so the slide changes every
// rotation — with the headline counts and a records list on the right. Every
// list shows as many rows as fit (priority order, lowest dropped) so the slide
// never scrolls on the big screen.

export function VenueStats({
  insights,
  scoreboard,
  activity,
  unitPx,
}: {
  insights: PublicInsights;
  scoreboard: PublicScoreboard;
  activity: PublicActivity | undefined;
  unitPx: number;
}) {
  const records = useRecordRows(insights, scoreboard, activity);
  const categories = insights.categories;

  // The side column hands out its height top-down, in priority order, from
  // measured sizes: the count tiles (dropped first when they'd leave no room
  // for a record), then as many records as fit, then as many category bars as
  // fit in what's left. Explicit rather than flex-shrink so the lowest block
  // gives way first, and so a block never ends up sized by its own content —
  // which would stop it growing back when space returns (the zoom keys).
  const { ref: columnRef, height: columnHeight } = useBoxSize();
  const { probe, heights } =
    useHeights<"tiles" | "recordsHead" | "recordRow" | "catHead" | "catRow">();
  const blockGap = 1.5 * unitPx;
  const rowGap = 0.5 * unitPx;
  const h = (key: keyof typeof heights) => heights[key] ?? 0;
  const unmeasured = columnHeight === 0;

  const showTiles =
    unmeasured || columnHeight >= h("tiles") + blockGap + h("recordsHead") + h("recordRow");
  let available = columnHeight - (showTiles ? h("tiles") + blockGap : 0);
  const recordCount = unmeasured
    ? records.length
    : fitCount(available - h("recordsHead"), h("recordRow"), rowGap, records.length);
  if (records.length > 0) {
    const shown = Math.max(1, recordCount); // the probe row is always rendered
    available -= h("recordsHead") + shown * h("recordRow") + (shown - 1) * rowGap + blockGap;
  }
  const categoryCount = unmeasured
    ? categories.length
    : fitCount(available - h("catHead"), h("catRow"), rowGap, categories.length);

  return (
    <div className="flex h-full min-h-0 gap-[2em]">
      <SolveTicker solves={activity?.recent_solves ?? []} unitPx={unitPx} />
      <div
        ref={columnRef}
        className="flex min-h-0 w-[40%] flex-shrink-0 flex-col gap-[1.5em] overflow-hidden"
      >
        {showTiles && <CountTiles stats={insights.stats} tilesRef={probe("tiles")} />}
        <Records
          rows={records}
          count={recordCount}
          headRef={probe("recordsHead")}
          rowRef={probe("recordRow")}
        />
        <Categories
          categories={categories}
          count={categoryCount}
          headRef={probe("catHead")}
          rowRef={probe("catRow")}
        />
      </div>
    </div>
  );
}

type Ref = (el: HTMLElement | null) => void;

function SectionTitle({
  children,
  hidden,
  headRef,
}: {
  children: React.ReactNode;
  hidden?: boolean;
  headRef?: Ref;
}) {
  // Hidden (not removed) alongside a list whose rows didn't fit, so the
  // heading never sits over nothing and the list keeps its box to re-measure.
  return (
    <h3
      ref={headRef}
      className={cn(
        "mb-[0.75em] text-[0.75em] font-semibold uppercase tracking-wide text-muted-foreground",
        hidden && "invisible",
      )}
    >
      {children}
    </h3>
  );
}

/** Newest first; as many rows as fit. Re-renders the "ago" labels on a slow
 *  tick so a row that was "just now" ages without a refetch. */
function SolveTicker({
  solves,
  unitPx,
}: {
  solves: PublicActivity["recent_solves"];
  unitPx: number;
}) {
  const t = useTranslations("scoreboard.public.venue");
  const format = useFormatter();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(id);
  }, []);
  const { containerRef, probeRef, count } = useFitCount<HTMLOListElement, HTMLLIElement>(
    solves.length,
  );

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col" aria-label={t("liveSolves")}>
      <SectionTitle hidden={solves.length > 0 && count === 0}>{t("liveSolves")}</SectionTitle>
      {solves.length === 0 ? (
        <div className="grid flex-1 place-items-center text-[1.25em] text-muted-foreground">
          {t("noSolvesYet")}
        </div>
      ) : (
        <ol ref={containerRef} className="flex min-h-0 flex-1 flex-col gap-[0.375em] overflow-hidden">
          {solves.slice(0, Math.max(1, count)).map((solve, i) => (
            <li
              key={`${solve.challenge_id}:${solve.subject_name}:${solve.solved_at}`}
              ref={i === 0 ? probeRef : undefined}
              className={cn(
                "flex items-center gap-[1em] rounded-lg px-[1em] py-[0.5em]",
                solve.is_first_blood && "bg-warning/10",
                count === 0 && "invisible",
              )}
            >
              <span className="w-[5.5em] flex-shrink-0 truncate whitespace-nowrap text-[0.75em] text-muted-foreground">
                {format.relativeTime(parseServerDate(solve.solved_at), { now, style: "narrow" })}
              </span>
              <span className="min-w-0 flex-1 truncate text-[1.125em]">
                {t.rich("solveRow", {
                  name: solve.subject_name,
                  title: solve.title,
                  b: (chunks) => <span className="font-semibold">{chunks}</span>,
                })}
              </span>
              {solve.is_first_blood && <FirstBloodIcon size={Math.round(1.1 * unitPx)} />}
              <span className="font-mono text-[1.125em] font-semibold tabular-nums text-primary">
                +{solve.points.toLocaleString()}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function CountTiles({ stats, tilesRef }: { stats: PublicInsights["stats"]; tilesRef: Ref }) {
  const t = useTranslations("scoreboard.public.insights");
  const tiles = [
    { label: t("participants"), value: stats.participants },
    { label: t("solves"), value: stats.solves },
    { label: t("challenges"), value: stats.challenges },
    { label: t("unsolved"), value: stats.unsolved },
  ];
  // Four across when the column is wide enough for the labels, else two by two
  // — a container query, since the column's width is what matters, not the
  // viewport's.
  return (
    <div ref={tilesRef} className="@container flex-shrink-0">
      <div className="grid grid-cols-2 gap-[0.75em] @[30em]:grid-cols-4">
      {tiles.map((tile) => (
        <div key={tile.label} className="rounded-lg border border-border px-[1em] py-[0.625em]">
          <div className="font-mono text-[1.5em] font-semibold tabular-nums">
            {tile.value.toLocaleString()}
          </div>
          <div className="truncate text-[0.75em] text-muted-foreground">{tile.label}</div>
        </div>
      ))}
      </div>
    </div>
  );
}

interface RecordRow {
  key: string;
  label: string;
  value: string;
  detail: string;
}

/** The highlight cards plus the race records, one row each, in priority
 *  order. */
function useRecordRows(
  insights: PublicInsights,
  scoreboard: PublicScoreboard,
  activity: PublicActivity | undefined,
): RecordRow[] {
  const t = useTranslations("scoreboard.public.venue");
  const ti = useTranslations("scoreboard.public.insights");
  const { most_solved, most_attempted, first_blood_leader, fastest_solve } = insights.highlights;
  const now = timelineEnd(insights.timeline);
  const race = closestRace(scoreboard.entries);
  const climb = biggestRankClimb(insights.timeline.series, CLIMB_WINDOW_MS, now);
  const streak = hotStreak(activity?.recent_solves ?? []);

  const rows = [
    first_blood_leader && {
      key: "firstBloods",
      label: ti("mostFirstBloods"),
      value: first_blood_leader.name,
      detail: ti("mostFirstBloodsDetail", { count: first_blood_leader.count }),
    },
    fastest_solve && {
      key: "fastest",
      label: ti("fastestSolve"),
      value: fastest_solve.name,
      detail: t("fastestSolveDetail", {
        title: fastest_solve.title,
        elapsed: formatElapsed(fastest_solve.seconds),
      }),
    },
    race && {
      key: "closest",
      label: t("closestRace"),
      // The names are the value (they get the room); the gap is the detail.
      value: t("closestRaceDetail", {
        upperRank: race.upper.rank,
        upper: race.upper.name,
        lowerRank: race.lower.rank,
        lower: race.lower.name,
      }),
      detail: race.gap === 0 ? t("tied") : t("pointsApart", { points: race.gap }),
    },
    streak && {
      key: "streak",
      label: t("hotStreak"),
      value: streak.name,
      detail: t("hotStreakDetail", { count: streak.count }),
    },
    climb && {
      key: "climb",
      label: t("biggestClimb"),
      value: climb.name,
      detail: t("biggestClimbDetail", { places: climb.places }),
    },
    most_solved && {
      key: "mostSolved",
      label: ti("mostSolved"),
      value: most_solved.title,
      detail: ti("mostSolvedDetail", { count: most_solved.count }),
    },
    most_attempted && {
      key: "mostAttempted",
      label: ti("mostAttempted"),
      value: most_attempted.title,
      detail: ti("mostAttemptedDetail", { count: most_attempted.count }),
    },
  ].filter(Boolean) as RecordRow[];
  return rows;
}

/** `count` rows of the records, as the column allotted; the first row is
 *  always rendered (invisible when nothing fits) so it can be measured. */
function Records({
  rows,
  count,
  headRef,
  rowRef,
}: {
  rows: RecordRow[];
  count: number;
  headRef: Ref;
  rowRef: Ref;
}) {
  const t = useTranslations("scoreboard.public.venue");
  if (rows.length === 0) return null;

  return (
    <section className="@container flex flex-shrink-0 flex-col" aria-label={t("records")}>
      <SectionTitle hidden={count === 0} headRef={headRef}>
        {t("records")}
      </SectionTitle>
      <div className="flex flex-col gap-[0.5em]">
        {rows.slice(0, Math.max(1, count)).map((row, i) => (
          <div
            key={row.key}
            ref={i === 0 ? rowRef : undefined}
            className={cn(
              "flex items-baseline gap-[1em] rounded-lg border border-border px-[1em] py-[0.5em]",
              count === 0 && "invisible",
            )}
          >
            <span className="w-[7em] flex-shrink-0 truncate text-[0.75em] text-muted-foreground @[36em]:w-[9.5em]">
              {row.label}
            </span>
            <span className="min-w-0 flex-1 truncate font-semibold" title={row.value}>
              {row.value}
            </span>
            <span
              className="min-w-0 max-w-[45%] flex-shrink truncate text-[0.75em] text-muted-foreground"
              title={row.detail}
            >
              {row.detail}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

/** One bar per category: solved challenges out of the visible total, with the
 *  solve count — the shape of the field, and where it's stuck. Untouched
 *  categories are called out. Lowest priority on the slide: it takes what the
 *  records leave, and shows as many rows as fit. */
function Categories({
  categories,
  count,
  headRef,
  rowRef,
}: {
  categories: PublicInsights["categories"];
  count: number;
  headRef: Ref;
  rowRef: Ref;
}) {
  const t = useTranslations("scoreboard.public.venue");
  if (categories.length === 0) return null;

  return (
    <section className="flex flex-shrink-0 flex-col" aria-label={t("categories")}>
      <SectionTitle hidden={count === 0} headRef={headRef}>
        {t("categories")}
      </SectionTitle>
      <div className="flex flex-col gap-[0.5em]">
        {categories.slice(0, Math.max(1, count)).map((c, i) => {
          const untouched = c.solved === 0;
          const share = c.challenges > 0 ? (c.solved / c.challenges) * 100 : 0;
          return (
            <div
              key={c.name ?? ""}
              ref={i === 0 ? rowRef : undefined}
              className={cn("flex items-center gap-[1em]", count === 0 && "invisible")}
            >
              <span className="w-[7em] flex-shrink-0 truncate text-[0.875em] @[36em]:w-[9.5em]">
                {c.name ?? t("uncategorised")}
              </span>
              <div
                className="h-[0.75em] min-w-0 flex-1 overflow-hidden rounded-full bg-secondary"
                role="meter"
                aria-valuemin={0}
                aria-valuemax={c.challenges}
                aria-valuenow={c.solved}
                aria-label={c.name ?? t("uncategorised")}
              >
                <div className="h-full rounded-full bg-primary" style={{ width: `${share}%` }} />
              </div>
              <span
                className={cn(
                  "w-[9em] flex-shrink-0 truncate text-right text-[0.75em] tabular-nums",
                  untouched ? "font-semibold text-warning" : "text-muted-foreground",
                )}
              >
                {untouched
                  ? t("untouched", { count: c.challenges })
                  : t("categorySolved", { solved: c.solved, total: c.challenges, solves: c.solves })}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
