// At-a-glance insight cards for the analytics page (#23) — pure derivation
// over the two reports the page already fetches, so no new endpoint and no
// extra requests (and, via the #18 activity room, they update live for free).
// Mirrors the lib/data-table.ts split: logic here, rendering in the page.
//
// This layer stays i18n-free: it returns the *winner* and the raw metric
// numbers, and the page renders the label/detail via next-intl (#248). That
// keeps the plural/format concerns in the message catalog, not baked into logic.

import type { ChallengeAnalytics, TeamAnalytics } from "@/lib/types";

/** Which of the four judge-question cards this is — the page maps it to a
 *  translated label and detail message. */
export type AnalyticsInsightKey =
  | "least_solved"
  | "most_attempted"
  | "most_tickets"
  | "most_first_bloods";

export interface AnalyticsInsight {
  key: AnalyticsInsightKey;
  /** The headline — a challenge title or competitor/team name (data, verbatim). */
  value: string;
  /** Numbers for the detail line's ICU message, keyed to match its placeholders. */
  detailParams: Record<string, number>;
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
      value: leastSolved.title,
      detailParams: {
        solves: leastSolved.solve_count,
        attempts: leastSolved.attempt_count,
      },
    });
  }

  const mostAttempted = maxBy(published, (c) => c.attempt_count);
  if (mostAttempted && mostAttempted.attempt_count > 0) {
    insights.push({
      key: "most_attempted",
      value: mostAttempted.title,
      detailParams: {
        attempts: mostAttempted.attempt_count,
        solves: mostAttempted.solve_count,
      },
    });
  }

  // Tickets exist on drafts too (a competitor can't see one, but staff link
  // them) — still filter to published for consistency with the other cards.
  const mostTickets = maxBy(published, (c) => c.ticket_count);
  if (mostTickets && mostTickets.ticket_count > 0) {
    insights.push({
      key: "most_tickets",
      value: mostTickets.title,
      detailParams: { count: mostTickets.ticket_count },
    });
  }

  const mostFirstBloods = maxBy(teams, (t) => t.first_bloods);
  if (mostFirstBloods && mostFirstBloods.first_bloods > 0) {
    insights.push({
      key: "most_first_bloods",
      value: mostFirstBloods.name,
      detailParams: {
        count: mostFirstBloods.first_bloods,
        rank: mostFirstBloods.rank,
      },
    });
  }

  return insights;
}
