"use client";

// One hook module per domain (ARCHITECTURE.md §8). Competitions.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { competitionsApi } from "@/lib/api";
import type { Competition } from "@/lib/types";
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
