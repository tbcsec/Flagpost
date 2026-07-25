// Geometry for the public points-over-time chart (#24) — pure maths, no React
// and no chart library (Flagpost ships none; the same dependency-free call as
// the scoreboard bar chart, survey histograms and the CSS scrollbars).
//
// Everything here maps domain values (a timestamp, a point total) onto a fixed
// SVG viewBox, so the component can stay declarative and this can be unit
// tested on its own.

export interface TimelinePoint {
  /** ISO timestamp from the API. */
  t: string;
  points: number;
}

export interface TimelineSeries {
  subject_id: string;
  name: string;
  points: TimelinePoint[];
}

/** The SVG coordinate space the chart draws into. Fixed and unitless — the
 *  rendered element scales it via `viewBox` + `width="100%"`. */
export interface ChartBox {
  width: number;
  height: number;
  padding: { top: number; right: number; bottom: number; left: number };
}

export const DEFAULT_BOX: ChartBox = {
  width: 960,
  height: 320,
  padding: { top: 12, right: 16, bottom: 28, left: 44 },
};

export interface Scales {
  /** Domain start/end as epoch milliseconds. */
  t0: number;
  t1: number;
  /** Max points on the y axis (already "nice"-rounded, never 0). */
  yMax: number;
  x: (t: number) => number;
  y: (points: number) => number;
}

const MS = (iso: string): number => new Date(iso).getTime();

/** Round a maximum up to a readable axis top (1/2/5 × 10ⁿ), so gridlines land
 *  on round numbers instead of the exact leader's score. */
export function niceMax(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalised = value / magnitude;
  const step = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10;
  return step * magnitude;
}

/** Build the x/y mappers for a set of series over a time window.
 *
 *  Degenerate inputs are handled rather than guarded at the call site: a zero
 *  width window (everything at one instant) or an all-zero board would divide
 *  by zero, so both collapse to a 1-unit domain and the line renders flat.
 */
export function buildScales(
  series: readonly TimelineSeries[],
  start: string | null,
  end: string | null,
  box: ChartBox = DEFAULT_BOX,
): Scales {
  const stamps = series.flatMap((s) => s.points.map((p) => MS(p.t)));
  const candidateStart = start ? MS(start) : Math.min(...stamps);
  const candidateEnd = end ? MS(end) : Math.max(...stamps);
  const t0 = Number.isFinite(candidateStart) ? candidateStart : 0;
  const rawT1 = Number.isFinite(candidateEnd) ? candidateEnd : t0;
  const t1 = rawT1 > t0 ? rawT1 : t0 + 1;

  const peak = series.reduce(
    (max, s) => s.points.reduce((m, p) => Math.max(m, p.points), max),
    0,
  );
  const yMax = niceMax(peak);

  const left = box.padding.left;
  const right = box.width - box.padding.right;
  const top = box.padding.top;
  const bottom = box.height - box.padding.bottom;

  return {
    t0,
    t1,
    yMax,
    x: (t) => left + ((t - t0) / (t1 - t0)) * (right - left),
    y: (points) => bottom - (points / yMax) * (bottom - top),
  };
}

/** A series as SVG `points` for a `<polyline>`.
 *
 *  Scores are step functions — a solve lands all at once — so each point emits
 *  a horizontal segment to the new time at the old value, then a vertical jump.
 *  Drawing straight diagonals would imply competitors trickle points in
 *  continuously, which would misrepresent the data. The line is extended to the
 *  window's end so every series reaches the right edge at its current total.
 */
export function seriesPolyline(series: TimelineSeries, scales: Scales): string {
  if (series.points.length === 0) return "";
  const coords: string[] = [];
  let previous = series.points[0].points;
  for (const point of series.points) {
    const at = Math.min(Math.max(MS(point.t), scales.t0), scales.t1);
    coords.push(`${scales.x(at)},${scales.y(previous)}`);
    coords.push(`${scales.x(at)},${scales.y(point.points)}`);
    previous = point.points;
  }
  coords.push(`${scales.x(scales.t1)},${scales.y(previous)}`);
  return coords.join(" ");
}

/** Evenly spaced y-axis gridlines (including 0 and the top). */
export function yTicks(scales: Scales, count = 4): { value: number; y: number }[] {
  return Array.from({ length: count + 1 }, (_, i) => {
    const value = Math.round((scales.yMax / count) * i);
    return { value, y: scales.y(value) };
  });
}

/** Evenly spaced x-axis ticks as epoch ms (the component formats the labels). */
export function xTicks(scales: Scales, count = 4): { at: number; x: number }[] {
  return Array.from({ length: count + 1 }, (_, i) => {
    const at = scales.t0 + ((scales.t1 - scales.t0) / count) * i;
    return { at, x: scales.x(at) };
  });
}

/** The palette token for a series index — `--chart-1` … `--chart-10`, wrapping
 *  if a caller ever plots more than the ten the API returns. */
export function seriesColor(index: number): string {
  return `hsl(var(--chart-${(index % 10) + 1}))`;
}
