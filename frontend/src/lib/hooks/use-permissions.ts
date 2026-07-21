"use client";

// One hook module per domain (ARCHITECTURE.md §8). The current user's effective
// permissions, used to gate nav/sections honestly instead of showing everything.

import { useQuery } from "@tanstack/react-query";

import { authApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

export function usePermissions() {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["permissions"],
    queryFn: authApi.permissions,
    enabled: isAuthenticated,
    staleTime: 5 * 60_000,
  });
}

/** Derived access flags for the active competition. `has()` checks the caller's
 *  effective set (`global ∪ by_competition[active]`); the flags map that onto
 *  the nav/section gates the shell needs. Until permissions load, `ready` is
 *  false and the flags are conservative (false). */
export function useAccess() {
  const { data } = usePermissions();
  const activeId = useAuthStore((s) => s.activeCompetitionId);

  const global = new Set(data?.global ?? []);
  const scoped = new Set(
    activeId ? (data?.by_competition[activeId] ?? []) : [],
  );
  const has = (key: string) => global.has(key) || scoped.has(key);

  const memberCompetitionCount = Object.keys(data?.by_competition ?? {}).length;
  const isAdmin =
    global.has("manage_users") ||
    global.has("manage_roles") ||
    global.has("create_competition");

  return {
    ready: Boolean(data),
    has,
    isAdmin,
    // Judge/organiser of the active competition.
    canManageActiveCompetition:
      has("edit_competition") || has("challenge_create") || has("challenge_edit"),
    canViewAnalytics:
      has("view_global_analytics") || has("view_competition_analytics"),
    // A signed-in user with no competition access yet belongs in the lobby.
    inLobby: !isAdmin && memberCompetitionCount === 0,
  };
}
