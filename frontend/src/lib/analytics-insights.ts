// At-a-glance insight cards for the analytics page (#23) — pure derivation
// over the two reports the page already fetches, so no new endpoint and no
// extra requests (and, via the #18 activity room, they update live for free).
// Mirrors the lib/data-table.ts split: logic here, rendering in the page.

import type { ChallengeAnalytics, TeamAnalytics } from "@/lib/types";

export interface AnalyticsInsight {
  key: string;
  label: string;
  /** The headline — a challenge title or competitor/team name. */
  value: string;
  detail: string;
}

/** Highest `metric` wins; ties break toward the earlier row (tables arrive
 *  rank/title-ordered, so the tie-break is stable and sensible). */
function maxBy<T>(rows: T[], metric: (row: T) => number): T | null {
  let best: T | null = null;
  for (const row of rows) {
    if (best === null || metric(row) > metric(best)) best = row;
  }
  return best;
}

/** The four judge-question cards, in display order. A card is omitted (not
 *  zero-filled) when its question has no meaningful answer yet — e.g. "most
 *  tickets" with zero tickets anywhere. */
export function analyticsInsights(
  challenges: ChallengeAnalytics[],
  teams: TeamAnalytics[],
): AnalyticsInsight[] {
  const insights: AnalyticsInsight[] = [];
  // Drafts always sit at zero solves, so they'd win "least solved" without
  // meaning anything — judge insights are about what competitors can play.
  const published = challenges.filter((c) => c.state === "published");

  // Least solved — the "nobody is cracking X" signal. Ties break toward the
  // most-attempted (tried a lot yet unsolved is the interesting case).
  let leastSolved: ChallengeAnalytics | null = null;
  for (const c of published) {
    if (
      leastSolved === null ||
      c.solve_count < leastSolved.solve_count ||
      (c.solve_count === leastSolved.solve_count &&
        c.attempt_count > leastSolved.attempt_count)
    ) {
      leastSolved = c;
    }
  }
  if (leastSolved) {
    insights.push({
      key: "least_solved",
      label: "Least solved",
      value: leastSolved.title,
      detail: `${leastSolved.solve_count} solves · ${leastSolved.attempt_count} attempts`,
    });
  }

  const mostAttempted = maxBy(published, (c) => c.attempt_count);
  if (mostAttempted && mostAttempted.attempt_count > 0) {
    insights.push({
      key: "most_attempted",
      label: "Most attempted",
      value: mostAttempted.title,
      detail: `${mostAttempted.attempt_count} attempts · ${mostAttempted.solve_count} solves`,
    });
  }

  // Tickets exist on drafts too (a competitor can't see one, but staff link
  // them) — still filter to published for consistency with the other cards.
  const mostTickets = maxBy(published, (c) => c.ticket_count);
  if (mostTickets && mostTickets.ticket_count > 0) {
    insights.push({
      key: "most_tickets",
      label: "Most tickets",
      value: mostTickets.title,
      detail: `${mostTickets.ticket_count} ticket${mostTickets.ticket_count === 1 ? "" : "s"}`,
    });
  }

  const mostFirstBloods = maxBy(teams, (t) => t.first_bloods);
  if (mostFirstBloods && mostFirstBloods.first_bloods > 0) {
    insights.push({
      key: "most_first_bloods",
      label: "Most first bloods",
      value: mostFirstBloods.name,
      detail: `${mostFirstBloods.first_bloods} first blood${
        mostFirstBloods.first_bloods === 1 ? "" : "s"
      } · rank #${mostFirstBloods.rank}`,
    });
  }

  return insights;
}
