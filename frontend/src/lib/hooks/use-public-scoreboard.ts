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

/** Recent awarded solves, first-bloods tagged (#77). Polled faster than the
 *  30s board so a first-blood splash lands within a few seconds of the solve;
 *  only enabled while venue mode is on, so the static page adds no extra load. */
export function usePublicActivity(
  competitionId: string,
  { enabled = true }: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: ["public-activity", competitionId],
    queryFn: () => publicApi.activity(competitionId),
    enabled: enabled && Boolean(competitionId),
    refetchInterval: 7_000,
  });
}

/** The /public directory of competitions offering a public scoreboard. */
export function usePublicCompetitions() {
  return useQuery({
    queryKey: ["public-competitions"],
    queryFn: () => publicApi.competitions(),
  });
}
