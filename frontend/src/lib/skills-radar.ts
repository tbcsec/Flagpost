// Radar/spider geometry for the cross-competition skills web (#364, ADR-0039).
//
// Pure math, no React and no SVG — the same split as lib/timeline-chart.ts, so
// it's unit-testable in isolation. Given a set of (skill, score) axes it lays
// them out evenly around a circle starting at the top and going clockwise, and
// scales each score to a radius against the strongest axis (so the web fills the
// chart and reads as a *balance* of strengths; the absolute totals live in the
// table beside it). Colours are the shared --chart-N tokens, never raw hex.

export interface SkillDatum {
  skill: string;
  score: number;
}

export interface RadarAxis {
  skill: string;
  score: number;
  angle: number; // radians, 0 = right, -PI/2 = top
  axisX: number; // spoke end, on the outer ring
  axisY: number;
  pointX: number; // the data point, scaled by score/maxScore
  pointY: number;
  labelX: number;
  labelY: number;
  labelAnchor: "start" | "middle" | "end";
}

export interface RadarGeometry {
  size: number;
  cx: number;
  cy: number;
  radius: number;
  maxScore: number;
  axes: RadarAxis[];
  polygon: string; // "x,y x,y …" — the data web
  rings: string[]; // concentric gridline polygons, innermost first
}

const DEFAULT_SIZE = 320;
const LABEL_GAP = 18; // px past the ring for axis labels
const RING_LEVELS = 4; // concentric gridlines

/** The outer-ring value: the strongest axis, floored at 1 so a lone single-solve
 *  web still renders (and never divides by zero). Unbounded — the web only grows. */
export function radarMax(scores: number[]): number {
  return Math.max(1, ...scores.map((s) => (Number.isFinite(s) ? s : 0)), 1);
}

/** The categorical token for axis ``index`` — ``hsl(var(--chart-N))`` (1..10),
 *  wrapping like the timeline's ``seriesColor``. */
export function axisColor(index: number): string {
  return `hsl(var(--chart-${(index % 10) + 1}))`;
}

function anchorFor(cos: number): "start" | "middle" | "end" {
  if (Math.abs(cos) < 0.3) return "middle";
  return cos > 0 ? "start" : "end";
}

/** Lay skills out around the circle. ``size`` is the square viewBox side. */
export function buildRadar(
  skills: SkillDatum[],
  { size = DEFAULT_SIZE }: { size?: number } = {},
): RadarGeometry {
  const cx = size / 2;
  const cy = size / 2;
  // Leave room for labels outside the ring.
  const radius = size / 2 - LABEL_GAP - 24;
  const maxScore = radarMax(skills.map((s) => s.score));
  const n = skills.length;

  const axes: RadarAxis[] = skills.map((s, i) => {
    // Start at the top (-90°) and step clockwise.
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(1, n);
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const r = (Math.max(0, s.score) / maxScore) * radius;
    return {
      skill: s.skill,
      score: s.score,
      angle,
      axisX: cx + radius * cos,
      axisY: cy + radius * sin,
      pointX: cx + r * cos,
      pointY: cy + r * sin,
      labelX: cx + (radius + LABEL_GAP) * cos,
      labelY: cy + (radius + LABEL_GAP) * sin,
      labelAnchor: anchorFor(cos),
    };
  });

  const polygon = axes.map((a) => `${round(a.pointX)},${round(a.pointY)}`).join(" ");

  const rings: string[] = [];
  for (let level = 1; level <= RING_LEVELS; level++) {
    const rr = (radius * level) / RING_LEVELS;
    rings.push(
      axes
        .map((a) => {
          const cos = Math.cos(a.angle);
          const sin = Math.sin(a.angle);
          return `${round(cx + rr * cos)},${round(cy + rr * sin)}`;
        })
        .join(" "),
    );
  }

  return { size, cx, cy, radius, maxScore, axes, polygon, rings };
}

function round(n: number): number {
  return Math.round(n * 100) / 100;
}
