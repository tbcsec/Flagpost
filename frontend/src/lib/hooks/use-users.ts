"use client";

// One hook module per domain (ARCHITECTURE.md §8). Users/auth actions.

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { authApi } from "@/lib/api";
import type { TokenResponse } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

export function useRegister() {
  const setSession = useAuthStore((s) => s.setSession);
  return useMutation({
    mutationFn: authApi.register,
    onSuccess: (data: TokenResponse) => setSession(data.access_token, data.user),
  });
}

export function useLogin() {
  const setSession = useAuthStore((s) => s.setSession);
  return useMutation({
    mutationFn: authApi.login,
    onSuccess: (data: TokenResponse) => setSession(data.access_token, data.user),
  });
}

export function useChangePassword() {
  return useMutation({ mutationFn: authApi.changePassword });
}

export function useLogout() {
  const clearSession = useAuthStore((s) => s.clearSession);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => {
      clearSession();
      // Drop all cached server state on logout so a next user starts clean.
      queryClient.clear();
    },
  });
}
