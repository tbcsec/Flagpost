// Pure helpers behind the venue race panel, the records list and the
// fit-to-screen rule (#513). Everything derives from data the public spectator
// endpoints already serve — the board, the top-entrant timeline and the
// recent-solves feed — so the disclosure surface is unchanged and the maths is
// unit-testable without rendering or timers.

import { parseServerDate } from "@/lib/datetime";
import type { TimelineSeries } from "@/lib/timeline-chart";
import type { PublicRecentSolve, PublicScoreboard } from "@/lib/types";

type Entry = PublicScoreboard["entries"][number];

const ms = (iso: string): number => parseServerDate(iso).getTime();

/** A series' running total at `at`: the last point on or before it, else 0 —
 *  scores are step functions, which is also how the chart draws them. */
export function valueAt(series: TimelineSeries, at: number): number {
  let value = 0;
  for (const point of series.points) {
    if (ms(point.t) > at) break;
    value = point.points;
  }
  return value;
}

function total(series: TimelineSeries): number {
  return series.points[series.points.length - 1]?.points ?? 0;
}

/** The instant the timeline runs to — the freeze cutoff on a frozen board, else
 *  the server's "now" when it was computed — so a window like "the last 30
 *  minutes" is measured back from the data, not the viewer's clock. Falls
 *  back to the latest point if the API ever omits the end. */
export function timelineEnd(timeline: {
  end: string | null;
  series: readonly TimelineSeries[];
}): number {
  if (timeline.end) return ms(timeline.end);
  return timeline.series.reduce(
    (latest, s) => s.points.reduce((m, p) => Math.max(m, ms(p.t)), latest),
    0,
  );
}

/** 1st versus 2nd on the board, once someone has scored. A margin of 0 is a
 *  tie on points (the board's rank tie-break is solve time). */
export function leadMargin(
  entries: readonly Entry[],
): { leader: string; runnerUp: string; margin: number } | null {
  const [first, second] = entries;
  if (!first || !second || first.points <= 0) return null;
  return { leader: first.name, runnerUp: second.name, margin: first.points - second.points };
}

/** How many times the lead changed hands, replaying every series' points in
 *  time order, and who took it last. The first entrant to score isn't a change.
 *  A tie on points keeps the sitting leader, matching the board's tie-break
 *  (whoever got there first). Ties between two challengers passing the leader
 *  at the same instant are broken by subject id, so the answer is stable
 *  between polls.
 *
 *  The API downsamples a long series to a bounded number of points, so on a
 *  very busy event a lead that changed and changed back inside one sample
 *  bucket isn't seen — the count is a floor, never an overstatement. */
export function leadChanges(series: readonly TimelineSeries[]): {
  count: number;
  last: { name: string; at: number } | null;
} {
  const names = new Map(series.map((s) => [s.subject_id, s.name]));
  const events = series
    .flatMap((s) => s.points.map((p) => ({ at: ms(p.t), subject: s.subject_id, points: p.points })))
    .sort((a, b) => a.at - b.at || (a.subject < b.subject ? -1 : a.subject > b.subject ? 1 : 0));

  const totals = new Map<string, number>();
  let leader: string | null = null;
  let count = 0;
  let last: { name: string; at: number } | null = null;
  for (const event of events) {
    totals.set(event.subject, event.points);
    let top: string | null = null;
    let topPoints = 0;
    for (const [subject, points] of totals) {
      if (points > topPoints) {
        top = subject;
        topPoints = points;
      }
    }
    if (top === null) continue;
    if (leader === null) {
      leader = top;
      continue;
    }
    if ((totals.get(leader) ?? 0) >= topPoints) continue;
    leader = top;
    count += 1;
    last = { name: names.get(top) ?? top, at: event.at };
  }
  return { count, last };
}

/** Who gained the most points in the window ending at `now`, if anyone did.
 *  On a series the API has downsampled (hundreds of scoring events for one
 *  entrant) the value at the window's start is read from the last kept point
 *  before it, so the gain can include up to one sample bucket from just
 *  before the window — a rounding of "the last 30 minutes", not a leak. */
export function biggestClimber(
  series: readonly TimelineSeries[],
  windowMs: number,
  now: number,
): { name: string; gained: number } | null {
  let best: { name: string; gained: number } | null = null;
  for (const s of series) {
    const gained = total(s) - valueAt(s, now - windowMs);
    if (gained > 0 && (best === null || gained > best.gained)) best = { name: s.name, gained };
  }
  return best;
}

/** Competition ranking (1, 1, 3) of the series by a score, highest first. */
function ranks(series: readonly TimelineSeries[], score: (s: TimelineSeries) => number) {
  const scored = series.map((s) => ({ id: s.subject_id, points: score(s) }));
  const sorted = [...scored].sort((a, b) => b.points - a.points);
  const rank = new Map<string, number>();
  sorted.forEach((row, i) => {
    rank.set(row.id, i > 0 && sorted[i - 1].points === row.points ? rank.get(sorted[i - 1].id)! : i + 1);
  });
  return rank;
}

/** Who climbed the most places in the window ending at `now`, among the
 *  entrants the timeline carries (the top of the board). Entrants outside the
 *  timeline's top N aren't ranked here, so this is "biggest climb at the top of
 *  the board", which is what a spectator is watching anyway. */
export function biggestRankClimb(
  series: readonly TimelineSeries[],
  windowMs: number,
  now: number,
): { name: string; places: number } | null {
  const before = ranks(series, (s) => valueAt(s, now - windowMs));
  const after = ranks(series, total);
  let best: { name: string; places: number } | null = null;
  for (const s of series) {
    const places = (before.get(s.subject_id) ?? 0) - (after.get(s.subject_id) ?? 0);
    if (places > 0 && (best === null || places > best.places)) best = { name: s.name, places };
  }
  return best;
}

/** The two adjacent ranks with the smallest points gap, among entrants who
 *  have scored. A gap of 0 is a tie on points. */
export function closestRace(entries: readonly Entry[]): {
  upper: Entry;
  lower: Entry;
  gap: number;
} | null {
  const scored = entries.filter((e) => e.points > 0);
  let best: { upper: Entry; lower: Entry; gap: number } | null = null;
  for (let i = 1; i < scored.length; i += 1) {
    const gap = scored[i - 1].points - scored[i].points;
    if (best === null || gap < best.gap) best = { upper: scored[i - 1], lower: scored[i], gap };
  }
  return best;
}

/** The run of most-recent solves by one entrant (feed is newest-first): two
 *  or more in a row is a streak worth calling out. */
export function hotStreak(
  solves: readonly PublicRecentSolve[],
): { name: string; count: number } | null {
  const head = solves[0];
  if (!head) return null;
  let count = 0;
  for (const s of solves) {
    if (s.subject_name !== head.subject_name) break;
    count += 1;
  }
  return count >= 2 ? { name: head.subject_name, count } : null;
}

/** How many equal-height items fit in `available` with `gap` between them,
 *  capped at `max`. An unmeasured item (0 height — jsdom, or before layout)
 *  fits everything, so nothing is dropped on a guess. */
export function fitCount(available: number, itemSize: number, gap: number, max: number): number {
  if (max <= 0) return 0;
  if (!(itemSize > 0)) return max;
  const n = Math.floor((available + gap) / (itemSize + gap));
  return Math.max(0, Math.min(max, n));
}

/** Lay out the chart's end-of-line labels so none overlap: each label wants to
 *  sit at its line's end `y`, and gets pushed apart by at least `minGap`,
 *  within [top, bottom]. Pushes down first, then back up from the bottom if
 *  the stack ran off the chart — so the order of the labels always matches
 *  the order of the lines. */
export function stackLabels<T extends { id: string; y: number }>(
  items: readonly T[],
  minGap: number,
  top: number,
  bottom: number,
): Map<string, number> {
  const sorted = [...items].sort((a, b) => a.y - b.y);
  const ys = sorted.map((item) => Math.max(top, item.y));
  for (let i = 1; i < ys.length; i += 1) ys[i] = Math.max(ys[i], ys[i - 1] + minGap);
  if (ys.length > 0 && ys[ys.length - 1] > bottom) {
    ys[ys.length - 1] = bottom;
    for (let i = ys.length - 2; i >= 0; i -= 1) ys[i] = Math.min(ys[i], ys[i + 1] - minGap);
  }
  return new Map(sorted.map((item, i) => [item.id, ys[i]]));
}

