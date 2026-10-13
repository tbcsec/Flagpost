"use client";

// Cross-competition skills web (#364, ADR-0039). One hook per read: the caller's
// own web (Profile → Skills) and the admin users×skills matrix.

import { useMutation, useQuery } from "@tanstack/react-query";

import { skillsApi } from "@/lib/api";
import type { SkillMatrixQuery } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const skillsKeys = {
  mine: () => ["skills", "me"] as const,
  matrix: (q: SkillMatrixQuery) =>
    ["skills", "matrix", q.limit, q.offset, q.sort ?? "total", q.direction ?? "desc"] as const,
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
  return useMutation({ mutationFn: () => skillsApi.exportCsv() });
}
