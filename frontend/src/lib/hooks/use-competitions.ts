"use client";

// One hook module per domain (ARCHITECTURE.md §8). Competitions.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { competitionsApi } from "@/lib/api";
import type { Competition, CompetitionUpdate } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

// Query keys are namespaced by domain so invalidation stays scoped (§8).
const competitionKeys = {
  all: ["competitions"] as const,
  detail: (id: string) => ["competitions", id] as const,
};

export function useCompetitions() {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: competitionKeys.all,
    queryFn: competitionsApi.list,
    enabled: isAuthenticated,
  });
}

export function useCompetition(id: string) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: competitionKeys.detail(id),
    queryFn: () => competitionsApi.get(id),
    enabled: isAuthenticated && Boolean(id),
  });
}

/** The competition selected in the topbar switcher (stored in the auth store),
 *  resolved to its full record. The shell defaults it to the first available. */
export function useActiveCompetition() {
  const activeCompetitionId = useAuthStore((s) => s.activeCompetitionId);
  const query = useCompetition(activeCompetitionId ?? "");
  return { competitionId: activeCompetitionId, ...query };
}

/** Joining grants the competition-scoped Participant role, so we refresh both
 *  the competition list (visibility) and permissions (nav gating), and switch
 *  the active competition to the one just joined. */
function useOnJoined() {
  const queryClient = useQueryClient();
  const setActiveCompetition = useAuthStore((s) => s.setActiveCompetition);
  return (joined: Competition) => {
    queryClient.invalidateQueries({ queryKey: competitionKeys.all });
    queryClient.invalidateQueries({ queryKey: ["permissions"] });
    setActiveCompetition(joined.id);
  };
}

export function useJoinCompetition() {
  const onJoined = useOnJoined();
  return useMutation({
    mutationFn: (id: string) => competitionsApi.join(id),
    onSuccess: onJoined,
  });
}

export function useJoinByCode() {
  const onJoined = useOnJoined();
  return useMutation({
    mutationFn: (inviteCode: string) => competitionsApi.joinByCode(inviteCode),
    onSuccess: onJoined,
  });
}

export function useCreateCompetition() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: competitionsApi.create,
    // Mutations invalidate their own domain only; cross-domain invalidation is
    // explicit elsewhere, never a silent global flush (§8).
    onSuccess: (created: Competition) => {
      queryClient.invalidateQueries({ queryKey: competitionKeys.all });
      queryClient.setQueryData(competitionKeys.detail(created.id), created);
    },
  });
}

export function useCloneCompetition() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      competitionsApi.clone(id, name),
    onSuccess: (created: Competition) => {
      queryClient.invalidateQueries({ queryKey: competitionKeys.all });
      queryClient.setQueryData(competitionKeys.detail(created.id), created);
    },
  });
}

export function useArchiveCompetition() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, archived }: { id: string; archived: boolean }) =>
      archived ? competitionsApi.archive(id) : competitionsApi.unarchive(id),
    onSuccess: (updated: Competition) => {
      queryClient.setQueryData(competitionKeys.detail(updated.id), updated);
      queryClient.invalidateQueries({ queryKey: competitionKeys.all });
    },
  });
}

export function useDeleteCompetition() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => competitionsApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: competitionKeys.all });
      // A deleted competition may have been the active one; permissions change.
      queryClient.invalidateQueries({ queryKey: ["permissions"] });
    },
  });
}

export function useUpdateCompetition(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CompetitionUpdate) => competitionsApi.update(id, input),
    onSuccess: (updated: Competition) => {
      queryClient.setQueryData(competitionKeys.detail(id), updated);
      queryClient.invalidateQueries({ queryKey: competitionKeys.all });
    },
  });
}
