"use client";

// One hook module per domain (ARCHITECTURE.md §8). Challenges.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { challengesApi } from "@/lib/api";
import type { ChallengeCreate, ChallengeUpdate } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const challengeKeys = {
  list: (competitionId: string) => ["challenges", competitionId] as const,
  detail: (competitionId: string, id: string) =>
    ["challenges", competitionId, id] as const,
};

export function useChallenges(competitionId: string) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: challengeKeys.list(competitionId),
    queryFn: () => challengesApi.list(competitionId),
    enabled: isAuthenticated && Boolean(competitionId),
  });
}

export function useChallenge(competitionId: string, challengeId: string) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: challengeKeys.detail(competitionId, challengeId),
    queryFn: () => challengesApi.get(competitionId, challengeId),
    enabled: isAuthenticated && Boolean(competitionId) && Boolean(challengeId),
  });
}

function useInvalidate(competitionId: string) {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({
      queryKey: challengeKeys.list(competitionId),
    });
}

export function useCreateChallenge(competitionId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: (input: ChallengeCreate) =>
      challengesApi.create(competitionId, input),
    onSuccess: invalidate,
  });
}

export function useUpdateChallenge(competitionId: string, challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ChallengeUpdate) =>
      challengesApi.update(competitionId, challengeId, input),
    onSuccess: (updated) => {
      queryClient.setQueryData(
        challengeKeys.detail(competitionId, challengeId),
        updated,
      );
      queryClient.invalidateQueries({
        queryKey: challengeKeys.list(competitionId),
      });
    },
  });
}

/** Reset multiple-choice guesses (staff). Empty target = everyone. */
export function useResetGuesses(competitionId: string, challengeId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: (target: { user_id?: string; team_id?: string }) =>
      challengesApi.resetGuesses(competitionId, challengeId, target),
    onSuccess: invalidate,
  });
}

export function useChallengeStateMutation(competitionId: string) {
  const invalidate = useInvalidate(competitionId);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      challengeId,
      action,
    }: {
      challengeId: string;
      action: "publish" | "unpublish" | "delete";
    }) => {
      if (action === "publish")
        await challengesApi.publish(competitionId, challengeId);
      else if (action === "unpublish")
        await challengesApi.unpublish(competitionId, challengeId);
      else await challengesApi.remove(competitionId, challengeId);
    },
    onSuccess: (_data, { challengeId }) => {
      queryClient.removeQueries({
        queryKey: challengeKeys.detail(competitionId, challengeId),
      });
      invalidate();
    },
  });
}
