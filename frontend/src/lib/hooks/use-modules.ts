"use client";

// One hook module per domain (ARCHITECTURE.md §8). Per-competition module
// inventory + enable/disable (Admin → Plugins, §11.3). Module state is
// per-competition, so every key carries the competition id.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { modulesApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

/** The site-level optional-module catalog — the source for the at-creation
 *  module picker (#252). Competition-independent, so no id in the key. */
export function useModuleCatalog(enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["modules", "catalog"],
    queryFn: () => modulesApi.catalog(),
    enabled: isAuthenticated && enabled,
  });
}

export function useModules(competitionId: string, enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["modules", competitionId],
    queryFn: () => modulesApi.list(competitionId),
    enabled: isAuthenticated && enabled && Boolean(competitionId),
  });
}

/** The enabled optional-module ids for a competition — member-readable, so the
 *  nav can hide disabled modules' entries for every viewer. Its own query key
 *  (separate from the admin list) so a toggle can refresh both. */
export function useEnabledModules(competitionId: string, enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["modules", competitionId, "enabled"],
    queryFn: () => modulesApi.enabled(competitionId),
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
