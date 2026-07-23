"use client";

// One hook module per domain (ARCHITECTURE.md §8). Individual-mode participant
// roster — the counterpart to use-teams for competitions without teams.

import { useQuery } from "@tanstack/react-query";

import { participantsApi } from "@/lib/api";
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
