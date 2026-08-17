"use client";

// The public points-over-time chart (#24): cumulative score per top entrant,
// so a spectator can watch competitors climb and overtake each other.
//
// Hand-rolled inline SVG — Flagpost ships no chart library, matching the
// scoreboard's bar chart and the survey histograms. Geometry lives in
// lib/timeline-chart.ts (pure + unit-tested); this file is presentation only.

import { useTranslations } from "next-intl";
import * as React from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DEFAULT_BOX,
  buildScales,
  seriesColor,
  seriesPolyline,
  xTicks,
  yTicks,
  type TimelineSeries,
} from "@/lib/timeline-chart";

const { width, height, padding } = DEFAULT_BOX;

function clockLabel(at: number): string {
  return new Date(at).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function PointsTimeline({
  series,
  start,
  end,
  frozen,
}: {
  series: TimelineSeries[];
  start: string | null;
  end: string | null;
  frozen?: boolean;
}) {
  const t = useTranslations("scoreboard.public.timeline");
  // Hovering a legend entry (or focusing it by keyboard) dims the rest, which
  // is what makes ten overlapping lines readable.
  const [active, setActive] = React.useState<string | null>(null);

  const scored = series.filter((s) => s.points.some((p) => p.points > 0));
  if (scored.length === 0) return null;

  const scales = buildScales(scored, start, end);
  const leader = scored.reduce((best, s) => {
    const total = s.points[s.points.length - 1]?.points ?? 0;
    const bestTotal = best?.points[best.points.length - 1]?.points ?? -1;
    return total > bestTotal ? s : best;
  }, scored[0]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>
          {t("subtitle", { count: scored.length })}
          {frozen ? t("freezeSuffix") : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-[0.75em]">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width="100%"
          className="h-[16em] w-full sm:h-[20em]"
          role="img"
          aria-label={t("ariaLabel", {
            count: scored.length,
            leader: leader.name,
            points: leader.points[leader.points.length - 1]?.points ?? 0,
          })}
        >
          {/* Horizontal gridlines + y labels */}
          {yTicks(scales).map((tick) => (
            <g key={tick.value}>
              <line
                x1={padding.left}
                x2={width - padding.right}
                y1={tick.y}
                y2={tick.y}
                stroke="hsl(var(--border))"
                strokeWidth={1}
              />
              <text
                x={padding.left - 8}
                y={tick.y + 4}
                textAnchor="end"
                className="text-[11px]"
                fill="hsl(var(--muted-foreground))"
              >
                {tick.value}
              </text>
            </g>
          ))}

          {/* Time axis */}
          {xTicks(scales).map((tick) => (
            <text
              key={tick.at}
              x={tick.x}
              y={height - padding.bottom + 18}
              textAnchor="middle"
              className="text-[11px]"
              fill="hsl(var(--muted-foreground))"
            >
              {clockLabel(tick.at)}
            </text>
          ))}

          {scored.map((s, index) => (
            <polyline
              key={s.subject_id}
              points={seriesPolyline(s, scales)}
              fill="none"
              stroke={seriesColor(index)}
              strokeWidth={active === s.subject_id ? 3 : 2}
              strokeLinejoin="round"
              strokeLinecap="round"
              opacity={active === null || active === s.subject_id ? 1 : 0.2}
              className="transition-[opacity,stroke-width] duration-150"
            />
          ))}
        </svg>

        <ul className="flex flex-wrap gap-x-[1em] gap-y-[0.375em]">
          {scored.map((s, index) => (
            <li key={s.subject_id}>
              <button
                type="button"
                onMouseEnter={() => setActive(s.subject_id)}
                onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(s.subject_id)}
                onBlur={() => setActive(null)}
                className="flex items-center gap-[0.375em] rounded text-[0.75em] text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                <span
                  aria-hidden
                  className="h-[0.5em] w-[0.5em] flex-shrink-0 rounded-full"
                  style={{ backgroundColor: seriesColor(index) }}
                />
                {s.name}
              </button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
