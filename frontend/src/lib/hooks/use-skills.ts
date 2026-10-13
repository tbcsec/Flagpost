"use client";

// Cross-competition skills web (#364, ADR-0039). One hook per read: the caller's
// own web (Profile → Skills) and the admin users×skills matrix.

import { useMutation, useQuery } from "@tanstack/react-query";

import { skillsApi } from "@/lib/api";
import type { SkillMatrixQuery, SkillWindow } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const skillsKeys = {
  mine: () => ["skills", "me"] as const,
  matrix: (q: SkillMatrixQuery) =>
    [
      "skills", "matrix",
      q.limit, q.offset, q.sort ?? "total", q.direction ?? "desc", q.window ?? "all",
    ] as const,
  detail: (userId: string, window: SkillWindow) =>
    ["skills", "detail", userId, window] as const,
};

export function useMySkills(enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: skillsKeys.mine(),
    queryFn: skillsApi.mine,
    enabled: enabled && isAuthenticated,
  });
}

export function useSkillMatrix(query: SkillMatrixQuery, enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: skillsKeys.matrix(query),
    queryFn: () => skillsApi.matrix(query),
    enabled: enabled && isAuthenticated,
  });
}

/** Download the whole matrix as CSV — an authenticated blob fetch, not an
 *  <a href> (no bearer token on plain navigations). */
export function useExportSkillMatrix() {
  return useMutation({
    mutationFn: (window: SkillWindow = "all") => skillsApi.exportCsv(window),
  });
}

/** The admin drill-down (#440): one user's skills + recent solves. Fetched on
 *  demand when their row is opened. */
export function useAdminUserSkills(
  userId: string | null,
  window: SkillWindow,
  enabled = true,
) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: skillsKeys.detail(userId ?? "", window),
    queryFn: () => skillsApi.userDetail(userId ?? "", window),
    enabled: enabled && isAuthenticated && Boolean(userId),
  });
}
