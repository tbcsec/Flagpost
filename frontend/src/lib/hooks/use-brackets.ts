"use client";

// One hook module per domain (§8). Bracket/division self-selection.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { bracketsApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

const bracketKeys = {
  mine: (competitionId: string) => ["bracket", competitionId] as const,
};

/** The acting subject's chosen bracket. */
export function useMyBracket(competitionId: string, enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: bracketKeys.mine(competitionId),
    queryFn: () => bracketsApi.mine(competitionId),
    enabled: isAuthenticated && enabled && Boolean(competitionId),
  });
}

export function useSetBracket(competitionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (bracket: string | null) => bracketsApi.set(competitionId, bracket),
    onSuccess: (data) => {
      qc.setQueryData(bracketKeys.mine(competitionId), data);
      // The board labels each entry by bracket — refresh it.
      qc.invalidateQueries({ queryKey: ["scoreboard", competitionId] });
    },
  });
}
