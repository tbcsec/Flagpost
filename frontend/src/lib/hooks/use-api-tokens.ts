"use client";

// One hook module per domain (ARCHITECTURE.md §8). Personal API tokens (#75):
// admin mint/list/revoke-any (Admin → Users) + self list/revoke-own (Profile).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiTokensApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

export function useApiTokens() {
  const authed = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["api-tokens"],
    queryFn: apiTokensApi.list,
    enabled: authed,
  });
}

export function useMyApiTokens() {
  const authed = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["api-tokens", "mine"],
    queryFn: apiTokensApi.listMine,
    enabled: authed,
  });
}

export function useCreateApiToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: apiTokensApi.create,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-tokens"] }),
  });
}

export function useRevokeApiToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: apiTokensApi.revoke,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-tokens"] }),
  });
}

export function useRevokeMyApiToken() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: apiTokensApi.revokeMine,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-tokens"] }),
  });
}
