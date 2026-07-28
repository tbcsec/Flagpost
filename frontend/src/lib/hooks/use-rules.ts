"use client";

// One hook module per domain (ARCHITECTURE.md §8). Rules / code of conduct
// (#57): the effective document per competition, acceptance, and the two
// authoring surfaces (site-wide + the competition override lives on the
// competitions domain).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { rulesApi, siteSettingsApi } from "@/lib/api";
import type { CompetitionRules, RulesSettings } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const rulesKeys = {
  of: (competitionId: string) => ["rules", competitionId] as const,
  site: ["site-settings", "rules"] as const,
};

/** The effective rules + the caller's standing for a competition. Drives the
 *  in-app re-acceptance gate (`required`) and pre-join prompts. */
export function useCompetitionRules(competitionId: string, enabled = true) {
  const authed = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: rulesKeys.of(competitionId),
    queryFn: () => rulesApi.get(competitionId),
    enabled: authed && enabled && Boolean(competitionId),
  });
}

/** Imperative fetch for click-time gating (the lobby / team panel need the
 *  rules for an arbitrary competition the moment Join is pressed, not on
 *  render). Shares the query cache with useCompetitionRules. */
export function useFetchRules() {
  const queryClient = useQueryClient();
  return (competitionId: string): Promise<CompetitionRules> =>
    queryClient.fetchQuery({
      queryKey: rulesKeys.of(competitionId),
      queryFn: () => rulesApi.get(competitionId),
      // Always current at the gating moment — a stale "accepted" could let a
      // join fire into a 403 after a staff override reset.
      staleTime: 0,
    });
}

export function useAcceptRules() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (competitionId: string) => rulesApi.accept(competitionId),
    onSuccess: (data, competitionId) => {
      queryClient.setQueryData(rulesKeys.of(competitionId), data);
    },
  });
}

// --- Site-wide authoring (Admin → Site settings) ---

export function useRulesSettings() {
  const authed = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: rulesKeys.site,
    queryFn: siteSettingsApi.rules,
    enabled: authed,
  });
}

export function useUpdateRulesSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: RulesSettings) => siteSettingsApi.updateRules(input),
    onSuccess: (data) => {
      queryClient.setQueryData(rulesKeys.site, data);
      // The effective document may have changed for every competition using
      // the global text.
      queryClient.invalidateQueries({ queryKey: ["rules"] });
    },
  });
}
