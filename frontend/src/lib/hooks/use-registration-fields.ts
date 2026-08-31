"use client";

// One hook module per domain (ARCHITECTURE.md §8). Custom registration fields
// (#350): organiser-defined field definitions + an individual competitor's own
// answers. Team-mode answers travel with the team (use-teams).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { registrationFieldsApi } from "@/lib/api";
import type { RegistrationFieldInput, RegistrationValues } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const registrationFieldKeys = {
  defs: (competitionId: string) =>
    ["registration-fields", competitionId] as const,
  mine: (competitionId: string) =>
    ["registration-fields", competitionId, "me"] as const,
};

/** The competition's field definitions (form order). Any authenticated user may
 *  read them — the join / team-creation form renders from these. */
export function useRegistrationFields(competitionId: string) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: registrationFieldKeys.defs(competitionId),
    queryFn: () => registrationFieldsApi.list(competitionId),
    enabled: isAuthenticated && Boolean(competitionId),
  });
}

/** An individual competitor's own answers. Gated to members by the route (403
 *  otherwise); the caller enables it only when relevant. */
export function useMyRegistrationValues(
  competitionId: string,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: registrationFieldKeys.mine(competitionId),
    queryFn: () => registrationFieldsApi.getMine(competitionId),
    enabled: enabled && isAuthenticated && Boolean(competitionId),
  });
}

/** Replace the competition's field set (organiser). */
export function usePutRegistrationFields(competitionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (fields: RegistrationFieldInput[]) =>
      registrationFieldsApi.put(competitionId, fields),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: registrationFieldKeys.defs(competitionId),
      }),
  });
}

/** Download the organiser CSV of every subject's answers (#350). */
export function useExportRegistrationValues(competitionId: string) {
  return useMutation({
    mutationFn: async () => {
      const blob = await registrationFieldsApi.exportCsv(competitionId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `registration-fields-${competitionId}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    },
  });
}

/** An individual competitor edits their own answers. */
export function usePutMyRegistrationValues(competitionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (values: RegistrationValues) =>
      registrationFieldsApi.putMine(competitionId, values),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: registrationFieldKeys.mine(competitionId),
      }),
  });
}
