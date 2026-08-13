"use client";

// One hook module per domain (ARCHITECTURE.md §8). Hints (Phase 9).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { hintsApi } from "@/lib/api";
import type { HintUpdate } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const hintKeys = {
  list: (competitionId: string, challengeId: string) =>
    ["hints", competitionId, challengeId] as const,
};

export function useHints(competitionId: string, challengeId: string) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: hintKeys.list(competitionId, challengeId),
    queryFn: () => hintsApi.list(competitionId, challengeId),
    enabled:
      isAuthenticated && Boolean(competitionId) && Boolean(challengeId),
  });
}

function useInvalidateHints(competitionId: string, challengeId: string) {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({
      queryKey: hintKeys.list(competitionId, challengeId),
    });
}

/** Reveal a hint. Idempotent server-side (§13.2); on success the challenge's
 *  hints are refreshed (and the scoreboard updates live over its own room if
 *  a cost was charged). */
export function useRevealHint(competitionId: string, challengeId: string) {
  const invalidate = useInvalidateHints(competitionId, challengeId);
  return useMutation({
    mutationFn: (hintId: string) =>
      hintsApi.reveal(competitionId, challengeId, hintId),
    onSuccess: invalidate,
  });
}

export function useCreateHint(competitionId: string, challengeId: string) {
  const invalidate = useInvalidateHints(competitionId, challengeId);
  return useMutation({
    mutationFn: (input: {
      body: string;
      cost: number;
      hidden?: boolean;
      release_at?: string | null;
    }) => hintsApi.create(competitionId, challengeId, input),
    onSuccess: invalidate,
  });
}

/** Edit a hint, and/or publish it (#213): pass `{ hidden: false }` to release a
 *  hidden hint. Refreshes the list so the badge and visibility update. */
export function useUpdateHint(competitionId: string, challengeId: string) {
  const invalidate = useInvalidateHints(competitionId, challengeId);
  return useMutation({
    mutationFn: ({ hintId, patch }: { hintId: string; patch: HintUpdate }) =>
      hintsApi.update(competitionId, challengeId, hintId, patch),
    onSuccess: invalidate,
  });
}

export function useDeleteHint(competitionId: string, challengeId: string) {
  const invalidate = useInvalidateHints(competitionId, challengeId);
  return useMutation({
    mutationFn: (hintId: string) =>
      hintsApi.remove(competitionId, challengeId, hintId),
    onSuccess: invalidate,
  });
}
