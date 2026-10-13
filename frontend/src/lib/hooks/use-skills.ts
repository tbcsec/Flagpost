"use client";

// Cross-competition skills web (#364, ADR-0039). One hook per read: the caller's
// own web (Profile → Skills) and the admin users×skills matrix.

import { useQuery } from "@tanstack/react-query";

import { skillsApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

const skillsKeys = {
  mine: () => ["skills", "me"] as const,
  matrix: (limit: number, offset: number) =>
    ["skills", "matrix", limit, offset] as const,
};

export function useMySkills(enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: skillsKeys.mine(),
    queryFn: skillsApi.mine,
    enabled: enabled && isAuthenticated,
  });
}

export function useSkillMatrix(
  { limit, offset }: { limit: number; offset: number },
  enabled = true,
) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: skillsKeys.matrix(limit, offset),
    queryFn: () => skillsApi.matrix({ limit, offset }),
    enabled: enabled && isAuthenticated,
  });
}
