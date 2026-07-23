"use client";

// One hook module per domain (ARCHITECTURE.md §8). First-run setup (ADR-0017).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { setupApi } from "@/lib/api";
import type { SetupRequest, TokenResponse } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const SETUP_STATUS_KEY = ["setup", "status"] as const;

/** Whether the instance still needs first-run configuration. Public — drives the
 *  redirect to /setup. Rarely flips (once, at first run), so it's cached hard. */
export function useSetupStatus() {
  return useQuery({
    queryKey: SETUP_STATUS_KEY,
    queryFn: setupApi.status,
    staleTime: Infinity,
  });
}

/** Complete the wizard: create the owner + apply branding, then sign in. */
export function useCompleteSetup() {
  const setSession = useAuthStore((s) => s.setSession);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SetupRequest) => setupApi.complete(input),
    onSuccess: (data: TokenResponse) => {
      setSession(data.access_token, data.user);
      queryClient.setQueryData(SETUP_STATUS_KEY, { needs_setup: false });
      // Branding just changed — let the public site-settings refetch.
      queryClient.invalidateQueries({ queryKey: ["site-settings"] });
    },
  });
}
