"use client";

import { useTranslations } from "next-intl";

import { useBoxSize, useFitCount } from "@/components/public/venue/use-fit";
import { cn } from "@/lib/utils";
import {
  buildScales,
  gridDivisions,
  seriesColor,
  seriesPolyline,
  xTicks,
  yTicks,
  type TimelineSeries,
} from "@/lib/timeline-chart";
import type { PublicInsights, PublicScoreboard } from "@/lib/types";
import {
  biggestClimber,
  leadChanges,
  leadMargin,
  stackLabels,
  timelineEnd,
} from "@/lib/venue-race";

// The venue timeline slide (#513): the points-over-time chart *is* the slide —
// no card, no legend; it fills the box it's given and names each line at its
// right-hand end — with a race panel beside it that says what the lines mean:
// the margin at the top, how often the lead has changed hands, who's climbing.
// Everything on the panel derives from the series and board already fetched.

/** The climber window: long enough to span a quiet patch, short enough that
 *  "climbing" still means now. */
export const CLIMB_WINDOW_MS = 30 * 60 * 1000;

export function VenueTimeline({
  insights,
  scoreboard,
  unitPx,
}: {
  insights: PublicInsights;
  scoreboard: PublicScoreboard;
  /** The venue root's computed 1em, so SVG text scales with the slide. */
  unitPx: number;
}) {
  const t = useTranslations("scoreboard.public.venue");
  const scored = insights.timeline.series.filter((s) => s.points.some((p) => p.points > 0));
  // Priority order when the slide is narrow (a small display at a high zoom):
  // the chart keeps its room and the race panel is the block that goes — a
  // 16em panel plus the chart's own axis and label columns need ~44em.
  const { ref, width } = useBoxSize();
  const showRace = width === 0 || width >= RACE_PANEL_MIN_WIDTH_EM * unitPx;

  return (
    <div ref={ref} className="flex h-full min-h-0 gap-[2em]">
      <div className="min-h-0 min-w-0 flex-1">
        <FillChart
          series={scored}
          start={insights.timeline.start}
          end={insights.timeline.end}
          unitPx={unitPx}
        />
      </div>
      {showRace && (
        <RacePanel
          series={scored}
          entries={scoreboard.entries}
          // "The last 30 minutes" is measured back from where the series end —
          // the freeze cutoff on a frozen board — not from the wall clock.
          now={timelineEnd(insights.timeline)}
          title={t("race")}
        />
      )}
    </div>
  );
}

const RACE_PANEL_MIN_WIDTH_EM = 44;
/** The end-of-line label column (name + total). */
const LABEL_COLUMN_EM = 11;
/** The chart needs at least this much for its lines; below it the label
 *  column is dropped, and below it again nothing sensible can be drawn. */
const MIN_PLOT_EM = 8;
/** Vertical room each end-of-line label needs. */
const LABEL_GAP_EM = 1.3;

/** Wall-clock labels for the axis and the race panel — the browser's locale,
 *  as the static spectator chart already does, so the two agree. */
function clockLabel(at: number): string {
  return new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** The chart drawn at the box's real pixel size (measured, not a fixed
 *  viewBox), so text keeps its aspect and the lines use every pixel. */
function FillChart({
  series,
  start,
  end,
  unitPx,
}: {
  series: TimelineSeries[];
  start: string | null;
  end: string | null;
  unitPx: number;
}) {
  const t = useTranslations("scoreboard.public.venue");
  const { ref, width, height } = useBoxSize();
  const axisWidth = 3.25 * unitPx;
  const padTop = 0.75 * unitPx;
  const padBottom = 1.75 * unitPx;
  // Labels are the first thing dropped: when the box can't hold them beside a
  // readable plot, or isn't tall enough to stack one per line without
  // overlapping. The plot itself is never drawn narrower than zero.
  const withLabels =
    width - axisWidth - LABEL_COLUMN_EM * unitPx >= MIN_PLOT_EM * unitPx &&
    height - padTop - padBottom >= series.length * LABEL_GAP_EM * unitPx;
  const labelWidth = withLabels ? LABEL_COLUMN_EM * unitPx : 1 * unitPx;
  const box = {
    width,
    height,
    padding: { top: padTop, right: labelWidth, bottom: padBottom, left: axisWidth },
  };

  let body: React.ReactNode = null;
  if (width - axisWidth - labelWidth > 0 && height > 2.5 * unitPx && series.length > 0) {
    const scales = buildScales(series, start, end, box);
    const totals = series.map((s) => s.points[s.points.length - 1]?.points ?? 0);
    const leaderIndex = totals.indexOf(Math.max(...totals));
    const labelY = stackLabels(
      series.map((s, i) => ({ id: s.subject_id, y: scales.y(totals[i]) })),
      LABEL_GAP_EM * unitPx,
      box.padding.top + 0.5 * unitPx,
      height - box.padding.bottom - 0.5 * unitPx,
    );
    const rightEdge = width - box.padding.right;
    const small = 0.75 * unitPx;

    body = (
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={t("chartLabel", {
          count: series.length,
          leader: series[leaderIndex].name,
          points: totals[leaderIndex],
        })}
      >
        {yTicks(scales, gridDivisions(scales.yMax)).map((tick) => (
          <g key={tick.value}>
            <line
              x1={box.padding.left}
              x2={rightEdge}
              y1={tick.y}
              y2={tick.y}
              stroke="hsl(var(--border))"
              strokeWidth={1}
            />
            <text
              x={box.padding.left - 0.5 * unitPx}
              y={tick.y + small * 0.35}
              textAnchor="end"
              fontSize={small}
              fill="hsl(var(--muted-foreground))"
            >
              {tick.value.toLocaleString()}
            </text>
          </g>
        ))}
        {xTicks(scales).map((tick) => (
          <text
            key={tick.at}
            x={tick.x}
            y={height - box.padding.bottom + 1.25 * unitPx}
            textAnchor="middle"
            fontSize={small}
            fill="hsl(var(--muted-foreground))"
          >
            {clockLabel(tick.at)}
          </text>
        ))}
        {series.map((s, index) => (
          <polyline
            key={s.subject_id}
            points={seriesPolyline(s, scales)}
            fill="none"
            stroke={seriesColor(index)}
            strokeWidth={(index === leaderIndex ? 0.25 : 0.15) * unitPx}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
        {withLabels &&
          series.map((s, index) => {
            const y = labelY.get(s.subject_id) ?? scales.y(totals[index]);
            const leader = index === leaderIndex;
            const total = totals[index].toLocaleString();
            // Name then total on one line. The name is cut to the characters
            // that leave the total room inside the column, so the total — the
            // part that matters — is never what the edge clips.
            const nameStart = rightEdge + 0.6 * unitPx;
            const totalWidth = total.length * MONO_GLYPH_EM * small;
            const nameBudget = width - 0.25 * unitPx - totalWidth - 0.5 * unitPx - nameStart;
            const maxChars = Math.max(3, Math.floor(nameBudget / (GLYPH_EM * 0.85 * unitPx)));
            return (
              <g key={s.subject_id} data-testid="end-label">
                <circle
                  cx={rightEdge}
                  cy={scales.y(totals[index])}
                  r={0.2 * unitPx}
                  fill={seriesColor(index)}
                />
                <text
                  x={nameStart}
                  y={y + 0.3 * unitPx}
                  fontSize={0.85 * unitPx}
                  fontWeight={leader ? 600 : 500}
                  fill={leader ? "hsl(var(--primary))" : "hsl(var(--foreground))"}
                >
                  <tspan>{truncate(s.name, maxChars)}</tspan>
                  <tspan
                    dx={0.5 * unitPx}
                    fontSize={small}
                    fontWeight={500}
                    fill="hsl(var(--muted-foreground))"
                  >
                    {total}
                  </tspan>
                </text>
              </g>
            );
          })}
      </svg>
    );
  }

  return (
    <div ref={ref} className="h-full w-full overflow-hidden">
      {body}
    </div>
  );
}

/** Rough average glyph widths, in em, for budgeting label text without
 *  measuring: the UI face is ~0.55em per character, the mono face 0.6em. */
const GLYPH_EM = 0.55;
const MONO_GLYPH_EM = 0.6;

/** Cut a name to `max` characters (code points, so an emoji isn't split). */
function truncate(name: string, max: number): string {
  const chars = Array.from(name);
  return chars.length > max ? `${chars.slice(0, max - 1).join("")}…` : name;
}

/** The race read-out beside the chart, in priority order: the margin at the
 *  top, who's climbing, how the lead has moved. Rows that don't fit are
 *  dropped from the bottom. */
function RacePanel({
  series,
  entries,
  now,
  title,
}: {
  series: TimelineSeries[];
  entries: PublicScoreboard["entries"];
  now: number;
  title: string;
}) {
  const t = useTranslations("scoreboard.public.venue");

  const margin = leadMargin(entries);
  const climber = biggestClimber(series, CLIMB_WINDOW_MS, now);
  const changes = leadChanges(series);

  const rows = [
    margin && {
      key: "margin",
      label: t("leadMargin"),
      value: margin.margin === 0 ? t("tied") : `+${margin.margin.toLocaleString()}`,
      detail:
        margin.margin === 0
          ? t("leadMarginTiedDetail", { leader: margin.leader, runnerUp: margin.runnerUp })
          : t("leadMarginDetail", { leader: margin.leader, runnerUp: margin.runnerUp }),
    },
    climber && {
      key: "climber",
      label: t("biggestClimber"),
      value: `+${climber.gained.toLocaleString()}`,
      detail: climber.name,
    },
    series.length > 0 && {
      key: "changes",
      label: t("leadChanges"),
      value: String(changes.count),
      detail: changes.last
        ? t("lastLeadChange", { name: changes.last.name, time: clockLabel(changes.last.at) })
        : t("noLeadChanges"),
    },
  ].filter(Boolean) as { key: string; label: string; value: string; detail: string }[];

  const { containerRef, probeRef, count } = useFitCount(rows.length);
  if (rows.length === 0) return null;

  return (
    <aside className="flex w-[16em] flex-shrink-0 flex-col" aria-label={title}>
      <h3
        className={cn(
          "mb-[0.75em] text-[0.75em] font-semibold uppercase tracking-wide text-muted-foreground",
          count === 0 && "invisible",
        )}
      >
        {title}
      </h3>
      <div ref={containerRef} className="flex min-h-0 flex-1 flex-col gap-[0.75em] overflow-hidden">
        {rows.slice(0, Math.max(1, count)).map((row, i) => (
          <div
            key={row.key}
            ref={i === 0 ? probeRef : undefined}
            className={cn(
              "rounded-lg border border-border px-[1em] py-[0.75em]",
              count === 0 && "invisible",
            )}
          >
            <div className="text-[0.75em] text-muted-foreground">{row.label}</div>
            <div className="font-mono text-[1.75em] font-semibold tabular-nums text-primary">
              {row.value}
            </div>
            <div className="truncate text-[0.875em]" title={row.detail}>
              {row.detail}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
