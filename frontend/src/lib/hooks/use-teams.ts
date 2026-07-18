"use client";

// One hook module per domain (ARCHITECTURE.md §8). Teams.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, teamsApi } from "@/lib/api";
import type { MyTeam } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

// Keys carry the competition id so cache invalidation stays scoped (§8) and
// switching the active competition doesn't flush unrelated team data.
const teamKeys = {
  list: (competitionId: string) => ["teams", competitionId] as const,
  mine: (competitionId: string) => ["teams", competitionId, "me"] as const,
};

export function useTeams(competitionId: string) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: teamKeys.list(competitionId),
    queryFn: () => teamsApi.list(competitionId),
    enabled: isAuthenticated && Boolean(competitionId),
  });
}

export function useMyTeam(competitionId: string) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery<MyTeam | null>({
    queryKey: teamKeys.mine(competitionId),
    // 404 = not in a team: a normal state, mapped to null rather than an error.
    queryFn: async () => {
      try {
        return await teamsApi.me(competitionId);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
    enabled: isAuthenticated && Boolean(competitionId),
  });
}

function useInvalidateTeams(competitionId: string) {
  const queryClient = useQueryClient();
  // Own-domain invalidation only (§8): both the listing and "my team".
  return () =>
    queryClient.invalidateQueries({ queryKey: teamKeys.list(competitionId) });
}

export function useCreateTeam(competitionId: string) {
  const invalidate = useInvalidateTeams(competitionId);
  return useMutation({
    mutationFn: (input: { name: string }) =>
      teamsApi.create(competitionId, input),
    onSuccess: invalidate,
  });
}

export function useJoinTeam(competitionId: string) {
  const invalidate = useInvalidateTeams(competitionId);
  return useMutation({
    mutationFn: (input: { invite_code: string }) =>
      teamsApi.join(competitionId, input),
    onSuccess: invalidate,
  });
}

export function useLeaveTeam(competitionId: string) {
  const invalidate = useInvalidateTeams(competitionId);
  return useMutation({
    mutationFn: () => teamsApi.leave(competitionId),
    onSuccess: invalidate,
  });
}
