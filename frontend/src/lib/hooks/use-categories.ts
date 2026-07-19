"use client";

// One hook module per domain (ARCHITECTURE.md §8). Categories.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { categoriesApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

const categoryKeys = {
  list: (competitionId: string) => ["categories", competitionId] as const,
};

export function useCategories(competitionId: string) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: categoryKeys.list(competitionId),
    queryFn: () => categoriesApi.list(competitionId),
    enabled: isAuthenticated && Boolean(competitionId),
  });
}

export function useCreateCategory(competitionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string }) =>
      categoriesApi.create(competitionId, input),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: categoryKeys.list(competitionId),
      }),
  });
}

export function useDeleteCategory(competitionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (categoryId: string) =>
      categoriesApi.remove(competitionId, categoryId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: categoryKeys.list(competitionId),
      });
      // A deleted category uncategorizes challenges server-side (SET NULL), so
      // their cached view is now stale — explicit cross-domain invalidation (§8).
      queryClient.invalidateQueries({ queryKey: ["challenges", competitionId] });
    },
  });
}
