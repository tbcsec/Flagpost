"use client";

// One hook module per domain (ARCHITECTURE.md §8). Flag submission (Phase 6).

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { submissionsApi } from "@/lib/api";
import type { SubmitResult } from "@/lib/types";

/** Submit a flag for a challenge. On a correct solve, the challenge list/detail
 *  are invalidated so solve state + counts refresh. RBAC, rate limiting and
 *  scoring are all enforced server-side (§13.2); errors surface to the caller. */
export function useSubmitFlag(competitionId: string, challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (flag: string) =>
      submissionsApi.submit(competitionId, challengeId, flag),
    onSuccess: (result: SubmitResult) => {
      if (result.correct) {
        queryClient.invalidateQueries({
          queryKey: ["challenges", competitionId],
        });
      }
    },
  });
}
