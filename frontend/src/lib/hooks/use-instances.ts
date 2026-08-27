"use client";

// One hook module per domain (ARCHITECTURE.md §8) for challenge instancing
// (#266, ADR-0036). This slice is the admin site-infra config (Admin → Site
// settings → Instances); the competitor/staff surfaces follow.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { instancesAdminApi } from "@/lib/api";
import type { InstanceSettingsUpdate } from "@/lib/types";

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
