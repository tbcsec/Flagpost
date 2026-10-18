"use client";

// One hook module per domain (ARCHITECTURE.md §8). The current user's effective
// permissions, used to gate nav/sections honestly instead of showing everything.

import { useQuery } from "@tanstack/react-query";

import { GLOBAL_SCOPE_PERMISSIONS, hasAdminAccess } from "@/lib/admin-surfaces";
import { authApi } from "@/lib/api";
import type { Permissions } from "@/lib/types";
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
  const { data, isError } = usePermissions();
  const activeId = useAuthStore((s) => s.activeCompetitionId);
  // `failed`: permissions couldn't load, so nothing waiting on `ready` should
  // wait forever (the competition switcher's default selection, say).
  return { ...deriveAccess(data, activeId), failed: isError && !data };
}

/** The access flags from a permissions payload — pure, so the gates are
 *  unit-tested without a query client or a store. */
export function deriveAccess(data: Permissions | undefined, activeId: string | null) {
  const global = new Set(data?.global ?? []);
  const scoped = new Set(
    activeId ? (data?.by_competition[activeId] ?? []) : [],
  );
  const has = (key: string) => global.has(key) || scoped.has(key);
  // Global grants only — what the Admin section (global scope) is gated on.
  const hasGlobal = (key: string) => global.has(key);

  const memberCompetitionCount = Object.keys(data?.by_competition ?? {}).length;
  // A competition-scope grant held globally holds in every competition (an
  // Administrator holds them all), so its holder is in every competition.
  const seesEveryCompetition = [...global].some(
    (p) => !GLOBAL_SCOPE_PERMISSIONS.has(p),
  );
  const isMemberOf = (competitionId: string) =>
    seesEveryCompetition || Boolean(data?.by_competition[competitionId]);
  // Can open the Admin section: any global grant that unlocks one of its pages
  // (#477) — not just the users/roles/competitions trio, so a narrow delegate
  // (event log, auth providers, backups…) reaches the page their grant is for.
  const isAdmin = hasAdminAccess(hasGlobal);

  return {
    ready: Boolean(data),
    has,
    hasGlobal,
    isAdmin,
    // Judge/organiser of the active competition.
    canManageActiveCompetition:
      has("edit_competition") || has("challenge_create") || has("challenge_edit"),
    canViewAnalytics:
      has("view_global_analytics") || has("view_competition_analytics"),
    // A signed-in user with no competition access yet belongs in the lobby: no
    // membership anywhere, and no competition-scope grant held globally (an
    // Administrator holds them all, so they never land here; nor does a custom
    // global role that can moderate tickets everywhere). Independent of isAdmin
    // (#477) — a delegate holding only global-scope grants (the event log, say)
    // can open Admin and still needs the lobby to reach a competition.
    inLobby: memberCompetitionCount === 0 && !seesEveryCompetition,
    seesEveryCompetition,
    // Holds a role in this competition (or one that applies everywhere). The
    // switcher also lists public competitions you haven't joined (#478).
    isMemberOf,
    memberOfActive: activeId !== null && isMemberOf(activeId),
  };
}
