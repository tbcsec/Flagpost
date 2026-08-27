"use client";

// One hook module per domain (ARCHITECTURE.md §8) for challenge instancing
// (#266, ADR-0036). This slice is the admin site-infra config (Admin → Site
// settings → Instances); the competitor/staff surfaces follow.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, deploymentsApi, instancesAdminApi } from "@/lib/api";
import type {
  ChallengeDeploymentUpdate,
  InstanceSettingsUpdate,
} from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

// --- admin site infra config -------------------------------------------------

const INSTANCE_SETTINGS_KEY = ["instances", "settings"] as const;

export function useInstanceSettings() {
  return useQuery({
    queryKey: INSTANCE_SETTINGS_KEY,
    queryFn: instancesAdminApi.get,
    staleTime: 60_000,
  });
}

export function useUpdateInstanceSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: InstanceSettingsUpdate) => instancesAdminApi.update(input),
    onSuccess: (data) => queryClient.setQueryData(INSTANCE_SETTINGS_KEY, data),
  });
}

/** Run the provisioner's staged validate() against the saved config. Not cached
 *  — it makes live outbound calls, so it only runs on an explicit click. */
export function useTestInstanceConnection() {
  return useMutation({ mutationFn: () => instancesAdminApi.testConnection() });
}

// --- per-challenge deployment spec (authoring) -------------------------------

const deploymentKeys = {
  detail: (competitionId: string, challengeId: string) =>
    ["deployment", competitionId, challengeId] as const,
};

/** The challenge's deployment spec, or `null` when none is set yet (the GET
 *  404s in that case — treated as "no deployment", not an error, so the editor
 *  shows the empty/create state). */
export function useChallengeDeployment(competitionId: string, challengeId: string) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: deploymentKeys.detail(competitionId, challengeId),
    queryFn: async () => {
      try {
        return await deploymentsApi.get(competitionId, challengeId);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
    enabled: isAuthenticated && Boolean(competitionId) && Boolean(challengeId),
  });
}

export function useUpsertChallengeDeployment(
  competitionId: string,
  challengeId: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ChallengeDeploymentUpdate) =>
      deploymentsApi.upsert(competitionId, challengeId, input),
    onSuccess: (data) =>
      queryClient.setQueryData(
        deploymentKeys.detail(competitionId, challengeId),
        data,
      ),
  });
}

export function useDeleteChallengeDeployment(
  competitionId: string,
  challengeId: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => deploymentsApi.remove(competitionId, challengeId),
    onSuccess: () =>
      queryClient.setQueryData(
        deploymentKeys.detail(competitionId, challengeId),
        null,
      ),
  });
}
