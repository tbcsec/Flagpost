"use client";

// One hook module per domain (ARCHITECTURE.md §8). Site-admin overview — the
// cross-competition totals + health for Admin → Dashboard.

import { useQuery } from "@tanstack/react-query";

import { adminApi } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

export function useAdminOverview(enabled = true) {
  const authed = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["admin-overview"],
    queryFn: () => adminApi.overview(),
    enabled: authed && enabled,
  });
}
