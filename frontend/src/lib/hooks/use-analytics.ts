"use client";

// One hook module per domain (ARCHITECTURE.md §8). Challenge & team analytics
// (ROADMAP #23) — read-only reporting, staff-gated on the server.

import { useQuery } from "@tanstack/react-query";

import { analyticsApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

const analyticsKeys = {
  challenges: (competitionId: string) =>
    ["analytics", competitionId, "challenges"] as const,
  teams: (competitionId: string) =>
    ["analytics", competitionId, "teams"] as const,
};

export function useChallengeAnalytics(competitionId: string, enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: analyticsKeys.challenges(competitionId),
    queryFn: () => analyticsApi.challenges(competitionId),
    enabled: enabled && isAuthenticated && Boolean(competitionId),
  });
}

export function useTeamAnalytics(competitionId: string, enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: analyticsKeys.teams(competitionId),
    queryFn: () => analyticsApi.teams(competitionId),
    enabled: enabled && isAuthenticated && Boolean(competitionId),
  });
}
