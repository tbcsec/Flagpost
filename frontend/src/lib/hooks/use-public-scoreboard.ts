"use client";

// One hook module per domain (§8). The public spectator board — no auth gate,
// since the whole point is that a logged-out viewer can watch a public
// competition. Polls periodically (no socket) so a spectator page stays fresh.

import { useQuery } from "@tanstack/react-query";

import { publicApi } from "@/lib/api";

export function usePublicScoreboard(competitionId: string) {
  return useQuery({
    queryKey: ["public-scoreboard", competitionId],
    queryFn: () => publicApi.scoreboard(competitionId),
    enabled: Boolean(competitionId),
    refetchInterval: 30_000,
  });
}

/** Spectator stats, highlights and the points timeline (#24). Fetched
 *  separately from the board so the standings still render if it fails, and
 *  polled on the same cadence so the two stay in step. */
export function usePublicInsights(competitionId: string) {
  return useQuery({
    queryKey: ["public-insights", competitionId],
    queryFn: () => publicApi.insights(competitionId),
    enabled: Boolean(competitionId),
    refetchInterval: 30_000,
  });
}

/** The /public directory of competitions offering a public scoreboard. */
export function usePublicCompetitions() {
  return useQuery({
    queryKey: ["public-competitions"],
    queryFn: () => publicApi.competitions(),
  });
}
