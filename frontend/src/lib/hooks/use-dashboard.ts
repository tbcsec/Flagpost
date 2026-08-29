"use client";

// One hook module per domain (ARCHITECTURE.md §8). Operational dashboard (§10).
// Each widget fetches its own slice, so this exposes one hook per data source.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { dashboardApi } from "@/lib/api";
import type { DashboardLayoutEntry } from "@/lib/types";
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

// --- New manager sections (#332). Each is a small staff-gated read slice; the
// widget always fires its query (it's only mounted when in the manager's saved
// layout), and a caller without the backend permission just gets an empty card.

export function useUnsolvedChallenges(competitionId: string) {
  const authed = useAuthed();
  return useQuery({
    queryKey: ["dashboard", competitionId, "unsolved-challenges"],
    queryFn: () => dashboardApi.unsolvedChallenges(competitionId),
    enabled: authed && Boolean(competitionId),
  });
}

export function useDifficultyProgress(competitionId: string) {
  const authed = useAuthed();
  return useQuery({
    queryKey: ["dashboard", competitionId, "difficulty-progress"],
    queryFn: () => dashboardApi.difficultyProgress(competitionId),
    enabled: authed && Boolean(competitionId),
  });
}

export function useTeamActivity(competitionId: string) {
  const authed = useAuthed();
  return useQuery({
    queryKey: ["dashboard", competitionId, "team-activity"],
    queryFn: () => dashboardApi.teamActivity(competitionId),
    enabled: authed && Boolean(competitionId),
  });
}

export function useBruteForce(competitionId: string) {
  const authed = useAuthed();
  return useQuery({
    queryKey: ["dashboard", competitionId, "brute-force"],
    queryFn: () => dashboardApi.bruteForce(competitionId),
    enabled: authed && Boolean(competitionId),
  });
}

export function useModerationFeed(competitionId: string) {
  const authed = useAuthed();
  return useQuery({
    queryKey: ["dashboard", competitionId, "moderation-feed"],
    queryFn: () => dashboardApi.moderationFeed(competitionId),
    enabled: authed && Boolean(competitionId),
  });
}

export function useInstanceHealth(competitionId: string) {
  const authed = useAuthed();
  return useQuery({
    queryKey: ["dashboard", competitionId, "instance-health"],
    queryFn: () => dashboardApi.instanceHealth(competitionId),
    enabled: authed && Boolean(competitionId),
  });
}

// --- Layout customization (§10.2–10.5). Staff-gated (customize_dashboard); the
// caller passes `enabled` from its access check so a participant never fires
// the 403 request. `key` selects which dashboard (only "manager" today).

export function useDashboardLayout(competitionId: string, key: string, enabled: boolean) {
  const authed = useAuthed();
  return useQuery({
    queryKey: ["dashboard", competitionId, "layout", key],
    queryFn: () => dashboardApi.getLayout(competitionId, key),
    enabled: authed && enabled && Boolean(competitionId),
  });
}

export function useSaveDashboardLayout(competitionId: string, key: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (entries: DashboardLayoutEntry[]) =>
      dashboardApi.saveLayout(competitionId, key, entries),
    onSuccess: (data) => {
      qc.setQueryData(["dashboard", competitionId, "layout", key], data);
    },
  });
}

export function useResetDashboardLayout(competitionId: string, key: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => dashboardApi.resetLayout(competitionId, key),
    onSuccess: () => {
      qc.setQueryData(["dashboard", competitionId, "layout", key], null);
    },
  });
}
