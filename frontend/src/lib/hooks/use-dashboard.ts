"use client";

// One hook module per domain (ARCHITECTURE.md §8). Operational dashboard (§10).
// Each widget fetches its own slice, so this exposes one hook per data source.

import { useQuery } from "@tanstack/react-query";

import { dashboardApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

function useAuthed() {
  return useAuthStore((s) => s.status === "authenticated");
}

export function useDashboardStats(competitionId: string) {
  const authed = useAuthed();
  return useQuery({
    queryKey: ["dashboard", competitionId, "stats"],
    queryFn: () => dashboardApi.stats(competitionId),
    enabled: authed && Boolean(competitionId),
  });
}

export function useRecentSolves(competitionId: string) {
  const authed = useAuthed();
  return useQuery({
    queryKey: ["dashboard", competitionId, "recent-solves"],
    queryFn: () => dashboardApi.recentSolves(competitionId),
    enabled: authed && Boolean(competitionId),
  });
}

/** Staff-only (view_competition_analytics); pass `enabled` from the caller's
 *  access check so a participant's widget never fires the 403 request. */
export function useChallengeHealth(competitionId: string, enabled: boolean) {
  const authed = useAuthed();
  return useQuery({
    queryKey: ["dashboard", competitionId, "challenge-health"],
    queryFn: () => dashboardApi.challengeHealth(competitionId),
    enabled: authed && enabled && Boolean(competitionId),
  });
}

export function useMyStanding(competitionId: string) {
  const authed = useAuthed();
  return useQuery({
    queryKey: ["dashboard", competitionId, "me"],
    queryFn: () => dashboardApi.me(competitionId),
    enabled: authed && Boolean(competitionId),
  });
}
