"use client";

// One hook module per domain (ARCHITECTURE.md §8). Users/auth actions.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { authApi, usersApi } from "@/lib/api";
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

export function useForgotPassword() {
  return useMutation({ mutationFn: authApi.forgotPassword });
}

export function useResetPassword() {
  return useMutation({ mutationFn: authApi.resetPassword });
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

// --- Admin user management (Admin → Users, §7). The directory + lifecycle;
// every mutation invalidates the ["users"] prefix so the table refreshes.

export function useUsers(q: string) {
  const authed = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["users", q],
    queryFn: () => usersApi.list(q || undefined),
    enabled: authed,
  });
}

function useUsersInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["users"] });
}

export function useCreateUser() {
  const invalidate = useUsersInvalidate();
  return useMutation({ mutationFn: usersApi.create, onSuccess: invalidate });
}

export function useUpdateUser() {
  const invalidate = useUsersInvalidate();
  return useMutation({
    mutationFn: ({ id, ...input }: { id: string; display_name?: string; email?: string; password?: string }) =>
      usersApi.update(id, input),
    onSuccess: invalidate,
  });
}

export function useBanUser() {
  const invalidate = useUsersInvalidate();
  return useMutation({
    mutationFn: ({ id, banned }: { id: string; banned: boolean }) =>
      banned ? usersApi.ban(id) : usersApi.unban(id),
    onSuccess: invalidate,
  });
}

export function useDeleteUser() {
  const invalidate = useUsersInvalidate();
  return useMutation({ mutationFn: (id: string) => usersApi.remove(id), onSuccess: invalidate });
}
