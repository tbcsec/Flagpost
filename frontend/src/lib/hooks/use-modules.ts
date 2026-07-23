"use client";

// One hook module per domain (ARCHITECTURE.md §8). Per-competition module
// inventory + enable/disable (Admin → Plugins, §11.3). Module state is
// per-competition, so every key carries the competition id.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { modulesApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

export function useModules(competitionId: string, enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["modules", competitionId],
    queryFn: () => modulesApi.list(competitionId),
    enabled: isAuthenticated && enabled && Boolean(competitionId),
  });
}

export function useToggleModule(competitionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ moduleId, enabled }: { moduleId: string; enabled: boolean }) =>
      modulesApi.toggle(competitionId, moduleId, enabled),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["modules", competitionId] });
    },
  });
}
