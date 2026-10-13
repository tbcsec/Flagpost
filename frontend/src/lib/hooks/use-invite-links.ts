"use client";

// One hook module per domain (ARCHITECTURE.md §8). Competition invite links
// (#427): the organiser's list/create/revoke surface, plus the public landing's
// resolve + join (Phase 3).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { inviteLinksApi } from "@/lib/api";
import { useOnJoined } from "@/lib/hooks/use-competitions";
import type { InviteLinkInput, InviteLinkJoinInput } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const inviteLinkKeys = {
  list: (competitionId: string) => ["invite-links", competitionId] as const,
  resolve: (token: string) => ["invite-links", "resolve", token] as const,
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

/** Public landing resolve — anonymous (no auth gate: the whole point is a
 *  logged-out visitor opening a link). A dead/unknown link 404s; surface that
 *  as the error state rather than retrying it away. */
export function useInviteLinkResolve(token: string) {
  return useQuery({
    queryKey: inviteLinkKeys.resolve(token),
    queryFn: () => inviteLinksApi.resolve(token),
    enabled: Boolean(token),
    retry: false,
  });
}

/** Complete a join through a link. Lands the user in the same post-join state
 *  as every other join path (active competition switched, caches refreshed). */
export function useJoinViaInviteLink(token: string) {
  const onJoined = useOnJoined();
  return useMutation({
    mutationFn: (input: InviteLinkJoinInput = {}) =>
      inviteLinksApi.join(token, input),
    onSuccess: onJoined,
  });
}
