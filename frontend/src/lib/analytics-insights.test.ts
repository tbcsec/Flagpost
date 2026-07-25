import { describe, expect, it } from "vitest";

import { analyticsInsights } from "@/lib/analytics-insights";
import type { ChallengeAnalytics, TeamAnalytics } from "@/lib/types";

function challenge(over: Partial<ChallengeAnalytics>): ChallengeAnalytics {
  return {
    challenge_id: "c",
    title: "Chal",
    category: null,
    points: 100,
    state: "published",
    solve_count: 0,
    attempt_count: 0,
    fail_count: 0,
    completion_rate: 0,
    avg_solve_time_seconds: null,
    hints_used: 0,
    ticket_count: 0,
    avg_rating: null,
    rating_count: 0,
    ...over,
  };
}

function team(over: Partial<TeamAnalytics>): TeamAnalytics {
  return {
    subject_id: "t",
    name: "Team",
    rank: 1,
    points: 0,
    solve_count: 0,
    first_bloods: 0,
    ticket_count: 0,
    last_solve_at: null,
    ...over,
  };
}

function byKey(insights: ReturnType<typeof analyticsInsights>) {
  return Object.fromEntries(insights.map((i) => [i.key, i]));
}

describe("analyticsInsights", () => {
  it("picks the least-solved published challenge, ties broken toward most attempts", () => {
    const cards = byKey(
      analyticsInsights(
        [
          challenge({ challenge_id: "a", title: "Easy", solve_count: 9, attempt_count: 12 }),
          challenge({ challenge_id: "b", title: "Wall", solve_count: 1, attempt_count: 40 }),
          challenge({ challenge_id: "c", title: "Quiet", solve_count: 1, attempt_count: 2 }),
        ],
        [],
      ),
    );
    expect(cards.least_solved.value).toBe("Wall");
    expect(cards.least_solved.detail).toBe("1 solves · 40 attempts");
  });

  it("ignores drafts — a zero-solve draft must not win least-solved", () => {
    const cards = byKey(
      analyticsInsights(
        [
          challenge({ challenge_id: "d", title: "Draft", state: "draft", solve_count: 0 }),
          challenge({ challenge_id: "p", title: "Live", solve_count: 3, attempt_count: 5 }),
        ],
        [],
      ),
    );
    expect(cards.least_solved.value).toBe("Live");
  });

  it("picks most attempted and most tickets", () => {
    const cards = byKey(
      analyticsInsights(
        [
          challenge({ challenge_id: "a", title: "A", attempt_count: 3, ticket_count: 1 }),
          challenge({ challenge_id: "b", title: "B", attempt_count: 8, ticket_count: 4 }),
        ],
        [],
      ),
    );
    expect(cards.most_attempted.value).toBe("B");
    expect(cards.most_tickets.value).toBe("B");
    expect(cards.most_tickets.detail).toBe("4 tickets");
  });

  it("picks the first-blood leader from the subjects table", () => {
    const cards = byKey(
      analyticsInsights(
        [challenge({})],
        [
          team({ subject_id: "1", name: "Alpha", rank: 2, first_bloods: 1 }),
          team({ subject_id: "2", name: "Bravo", rank: 5, first_bloods: 3 }),
        ],
      ),
    );
    expect(cards.most_first_bloods.value).toBe("Bravo");
    expect(cards.most_first_bloods.detail).toBe("3 first bloods · rank #5");
  });

  it("singularizes correctly", () => {
    const cards = byKey(
      analyticsInsights(
        [challenge({ ticket_count: 1 })],
        [team({ first_bloods: 1 })],
      ),
    );
    expect(cards.most_tickets.detail).toBe("1 ticket");
    expect(cards.most_first_bloods.detail).toBe("1 first blood · rank #1");
  });

  it("omits cards whose question has no meaningful answer", () => {
    // No attempts, no tickets, no first bloods anywhere → only least-solved
    // (which is still informative: nothing has been solved).
    const insights = analyticsInsights([challenge({})], [team({})]);
    expect(insights.map((i) => i.key)).toEqual(["least_solved"]);
  });

  it("returns nothing at all for an empty competition", () => {
    expect(analyticsInsights([], [])).toEqual([]);
  });
});
