"use client";

// Cross-competition skills web (#364, ADR-0039): the caller's own web
// (Profile → Skills).

import { useQuery } from "@tanstack/react-query";

import { skillsApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

const skillsKeys = {
  mine: () => ["skills", "me"] as const,
};

export function useMySkills(enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: skillsKeys.mine(),
    queryFn: skillsApi.mine,
    enabled: enabled && isAuthenticated,
  });
}
