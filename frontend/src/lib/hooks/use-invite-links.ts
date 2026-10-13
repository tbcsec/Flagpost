"use client";

// One hook module per domain (ARCHITECTURE.md §8). Competition invite links
// (#427): the organiser's list/create/revoke surface.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { inviteLinksApi } from "@/lib/api";
import type { InviteLinkInput } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const inviteLinkKeys = {
  list: (competitionId: string) => ["invite-links", competitionId] as const,
};

export function useInviteLinks(competitionId: string) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: inviteLinkKeys.list(competitionId),
    queryFn: () => inviteLinksApi.list(competitionId),
    enabled: isAuthenticated && Boolean(competitionId),
  });
}

export function useCreateInviteLink(competitionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: InviteLinkInput) =>
      inviteLinksApi.create(competitionId, input),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: inviteLinkKeys.list(competitionId),
      }),
  });
}

export function useRevokeInviteLink(competitionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (linkId: string) =>
      inviteLinksApi.revoke(competitionId, linkId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: inviteLinkKeys.list(competitionId),
      }),
  });
}
