"use client";

// One hook module per domain (ARCHITECTURE.md §8). Challenge attachments.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { attachmentsApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

const attachmentKeys = {
  list: (competitionId: string, challengeId: string) =>
    ["attachments", competitionId, challengeId] as const,
};

export function useAttachments(competitionId: string, challengeId: string) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: attachmentKeys.list(competitionId, challengeId),
    queryFn: () => attachmentsApi.list(competitionId, challengeId),
    enabled: isAuthenticated && Boolean(competitionId) && Boolean(challengeId),
  });
}

export function useUploadAttachment(competitionId: string, challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) =>
      attachmentsApi.upload(competitionId, challengeId, file),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: attachmentKeys.list(competitionId, challengeId),
      }),
  });
}

export function useDeleteAttachment(competitionId: string, challengeId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (attachmentId: string) =>
      attachmentsApi.remove(competitionId, challengeId, attachmentId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: attachmentKeys.list(competitionId, challengeId),
      }),
  });
}

/** Fetch a fresh signed URL and open it — the URL is short-lived, never cached. */
export function useDownloadAttachment(
  competitionId: string,
  challengeId: string,
) {
  return useMutation({
    mutationFn: (attachmentId: string) =>
      attachmentsApi.signedUrl(competitionId, challengeId, attachmentId),
    onSuccess: ({ url }) => {
      window.open(url, "_blank", "noopener");
    },
  });
}
