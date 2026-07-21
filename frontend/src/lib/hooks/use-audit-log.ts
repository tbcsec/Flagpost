"use client";

// One hook module per domain (ARCHITECTURE.md §8). Admin audit log (§3.3).

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { auditLogApi } from "@/lib/api";
import type { AuditLogQuery } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

export function useAuditLog(query: AuditLogQuery) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["audit-log", query],
    queryFn: () => auditLogApi.list(query),
    enabled: isAuthenticated,
    // Keep the previous page visible while the next loads — smooth paging.
    placeholderData: keepPreviousData,
  });
}

/** Distinct event names present in the log — populates the filter dropdown. */
export function useAuditEventNames() {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["audit-log", "event-names"],
    queryFn: auditLogApi.eventNames,
    enabled: isAuthenticated,
    staleTime: 60_000,
  });
}
