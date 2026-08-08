"use client";

// One hook module per domain (ARCHITECTURE.md §8). Flag submission (Phase 6) +
// the staff submissions browser (ROADMAP #76) — a filterable, paginated read
// over raw submission attempts, separate from use-analytics.ts's aggregates.

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { submissionsApi } from "@/lib/api";
import type { SubmissionQuery, SubmitResult } from "@/lib/types";

/** Submit a flag for a challenge. The challenge list/detail are invalidated when
 *  solve state changes (a correct solve) or when a wrong multiple-choice guess
 *  dropped the subject's value under the penalty (#148), so the card grid
 *  reflects the reduced worth. RBAC, rate limiting and scoring are all enforced
 *  server-side (§13.2); errors surface to the caller. */
export function useSubmitFlag(competitionId: string, challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (flag: string) =>
      submissionsApi.submit(competitionId, challengeId, flag),
    onSuccess: (result: SubmitResult) => {
      if (result.correct || result.subject_value != null) {
        queryClient.invalidateQueries({
          queryKey: ["challenges", competitionId],
        });
      }
    },
  });
}

/** Staff submissions browser (ROADMAP #76): a filterable, paginated read over
 *  raw submission attempts, for dispute resolution. Gated `view_submissions`
 *  server-side; `enabled` lets the caller skip fetching before access is known. */
export function useSubmissionBrowser(
  competitionId: string,
  query: SubmissionQuery,
  enabled = true,
) {
  return useQuery({
    queryKey: ["submissions", competitionId, query],
    queryFn: () => submissionsApi.browse(competitionId, query),
    enabled: enabled && Boolean(competitionId),
    // Keep the previous page visible while the next loads — smooth paging.
    placeholderData: keepPreviousData,
  });
}

/** Export the filtered rows as a CSV download — for taking a dispute outside
 *  the platform. Triggers a browser download rather than returning data. */
export function useExportSubmissions(competitionId: string) {
  return useMutation({
    mutationFn: (query: SubmissionQuery) =>
      submissionsApi.exportCsv(competitionId, query),
  });
}
