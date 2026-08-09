"use client";

// One hook module per domain (ARCHITECTURE.md §8). Users/auth actions.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiAssetUrl, authApi, authProvidersApi, usersApi } from "@/lib/api";
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

export function useVerifyEmail() {
  return useMutation({ mutationFn: authApi.verifyEmail });
}

export function useResendVerification() {
  return useMutation({ mutationFn: authApi.resendVerification });
}

/** Add / change / clear your own email (#106). The endpoint returns the updated
 *  user, so push it into the store — the profile page derives the "verify your
 *  email" banner from `user.email_verified_at`, which any change resets. */
export function useChangeEmail() {
  const setUser = useAuthStore((s) => s.setUser);
  return useMutation({
    mutationFn: authApi.changeEmail,
    onSuccess: (user) => setUser(user),
  });
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

/** Mass CSV import (#171). One mutation drives both phases — `dryRun: true`
 *  previews without writing, the plain call commits — so the dialog's preview
 *  and confirm steps can't drift apart. Only a commit refreshes the table. */
export function useImportUsers() {
  const invalidate = useUsersInvalidate();
  return useMutation({
    mutationFn: (input: { file: File; dryRun: boolean; defaultCompetitionId?: string }) =>
      usersApi.importCsv(input.file, {
        dryRun: input.dryRun,
        defaultCompetitionId: input.defaultCompetitionId,
      }),
    onSuccess: (_report, input) => {
      if (!input.dryRun) invalidate();
    },
  });
}

/** Exchange the httpOnly refresh cookie for an in-memory access token.
 *  Used by the SSO callback page, which lands holding only the cookie the
 *  backend set — the access token is deliberately never put in a URL. */
export function useRestoreSession() {
  return useMutation({ mutationFn: authApi.restore });
}

// --- external identity providers (#58, ADR-0021) ----------------------------

/** Enabled providers for the login page. Public, so it runs before auth and
 *  must not be gated on the auth store like the rest of this module. */
export function useAuthProviders() {
  return useQuery({
    queryKey: ["auth-providers", "public"],
    queryFn: authApi.providers,
    // A provider list changes about as often as an admin edits it; don't
    // refetch it on every focus of a login screen.
    staleTime: 60_000,
    retry: false,
    // Absolutize the login URL here rather than in the component: the SSO flow
    // is a full-page navigation to the *backend* origin, and components can't
    // import the API client (§8). Same approach use-site-settings takes for the
    // logo URL. The path is kind-aware so a SAML provider redirects to its own
    // transport.
    select: (providers) =>
      providers.map((p) => ({
        ...p,
        login_url: apiAssetUrl(`/api/auth/${p.kind}/${p.slug}/login`),
      })),
  });
}

const providerKeys = { admin: ["auth-providers", "admin"] as const };

export function useAdminAuthProviders() {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: providerKeys.admin,
    queryFn: authProvidersApi.list,
    enabled: isAuthenticated,
  });
}

function useInvalidateProviders() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["auth-providers"] });
}

export function useCreateAuthProvider() {
  const invalidate = useInvalidateProviders();
  return useMutation({ mutationFn: authProvidersApi.create, onSuccess: invalidate });
}

export function useUpdateAuthProvider() {
  const invalidate = useInvalidateProviders();
  return useMutation({
    mutationFn: ({ id, ...input }: { id: string } & Parameters<typeof authProvidersApi.update>[1]) =>
      authProvidersApi.update(id, input),
    onSuccess: invalidate,
  });
}

export function useDeleteAuthProvider() {
  const invalidate = useInvalidateProviders();
  return useMutation({ mutationFn: authProvidersApi.remove, onSuccess: invalidate });
}
