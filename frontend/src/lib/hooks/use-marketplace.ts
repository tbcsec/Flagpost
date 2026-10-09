"use client";

// One hook module per domain (ARCHITECTURE.md §8). The marketplace (#389,
// ADR-0040): the registry/trust config (Administrator-only) and the code-based
// resolve → install pipeline. Components never call the API client directly.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { marketplaceApi } from "@/lib/api";
import type { MarketplaceSettingsUpdate } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const SETTINGS_KEY = ["marketplace", "settings"] as const;

/** The registry + trust configuration. Gated server-side on manage_marketplace. */
export function useMarketplaceSettings(enabled = true) {
  const authed = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: SETTINGS_KEY,
    queryFn: marketplaceApi.getSettings,
    enabled: authed && enabled,
    staleTime: 5 * 60_000,
  });
}

export function useUpdateMarketplaceSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: MarketplaceSettingsUpdate) =>
      marketplaceApi.updateSettings(input),
    onSuccess: (data) => queryClient.setQueryData(SETTINGS_KEY, data),
  });
}

/** Resolve an import code to its confirmation payload — no install. */
export function useResolveCode() {
  return useMutation({
    mutationFn: (code: string) => marketplaceApi.resolve(code),
  });
}

/** Fetch → verify → install the resolved artifact (server-side pipeline). */
export function useInstallFromCode() {
  return useMutation({
    mutationFn: (input: { code: string; competition_id?: string | null }) =>
      marketplaceApi.install(input),
  });
}
