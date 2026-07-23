"use client";

// One hook module per domain (ARCHITECTURE.md §8). Individual-mode participant
// roster — the counterpart to use-teams for competitions without teams.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { participantsApi } from "@/lib/api";
import type { AwardInput } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

/** The individual-mode roster for a competition. `enabled` lets the caller skip
 *  the request in team-mode competitions (where teams are the surface). */
export function useParticipants(competitionId: string, enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["participants", competitionId],
    queryFn: () => participantsApi.list(competitionId),
    enabled: isAuthenticated && enabled && Boolean(competitionId),
  });
}

/** Grant a manual award (score_override). Refreshes the roster + scoreboard so
 *  the new points show immediately. */
export function useCreateAward(competitionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AwardInput) => participantsApi.award(competitionId, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["participants", competitionId] });
      qc.invalidateQueries({ queryKey: ["scoreboard", competitionId] });
    },
  });
}
