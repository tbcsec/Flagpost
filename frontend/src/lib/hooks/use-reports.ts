"use client";

// One hook module per domain (ARCHITECTURE.md §8). Post-event reports (#134,
// ADR-0030). Server state via TanStack Query; components never touch @/lib/api.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { reportsApi } from "@/lib/api";
import type { ReportCreate } from "@/lib/types";

const reportKeys = {
  catalog: (competitionId: string) => ["reports", competitionId, "catalog"] as const,
  list: (competitionId: string) => ["reports", competitionId, "list"] as const,
};

/** The section/preset/format catalog for the settings tab (rarely changes). */
export function useReportCatalog(competitionId: string, enabled = true) {
  return useQuery({
    queryKey: reportKeys.catalog(competitionId),
    queryFn: () => reportsApi.catalog(competitionId),
    enabled: Boolean(competitionId) && enabled,
    staleTime: 5 * 60_000,
  });
}

/** The generation history. Polls while any report is still rendering so its
 *  status and download links refresh on their own. */
export function useReports(competitionId: string, enabled = true) {
  return useQuery({
    queryKey: reportKeys.list(competitionId),
    queryFn: () => reportsApi.list(competitionId),
    enabled: Boolean(competitionId) && enabled,
    refetchInterval: (query) => {
      const generating = query.state.data?.some(
        (r) => r.status === "pending" || r.status === "running",
      );
      return generating ? 2500 : false;
    },
  });
}

export function useCreateReport(competitionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: ReportCreate) => reportsApi.create(competitionId, input),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: reportKeys.list(competitionId) }),
  });
}

export function useDeleteReport(competitionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reportId: string) => reportsApi.remove(competitionId, reportId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: reportKeys.list(competitionId) }),
  });
}

/** Download a ready report's PDF/HTML. The file is streamed through the API as
 *  an auth'd blob (not a presigned URL), so it works even where MinIO isn't
 *  browser-reachable — e.g. the tunnelled demo. */
export function useDownloadReport(competitionId: string) {
  return useMutation({
    mutationFn: (input: { reportId: string; fmt: "pdf" | "html"; version: number }) =>
      reportsApi.download(
        competitionId,
        input.reportId,
        input.fmt,
        `report-v${input.version}.${input.fmt}`,
      ),
  });
}
