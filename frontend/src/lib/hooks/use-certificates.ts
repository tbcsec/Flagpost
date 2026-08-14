"use client";

// One hook module per domain (ARCHITECTURE.md §8). Certificates (#219, ADR-0027).
// Server state via TanStack Query; components never touch @/lib/api directly.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  certificateAssetsApi,
  certificatesApi,
  meCertificatesApi,
} from "@/lib/api";
import type { CertificateTemplateInput } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const certKeys = {
  manifest: ["certificate-assets", "manifest"] as const,
  template: (competitionId: string) => ["certificates", competitionId, "template"] as const,
  fonts: (competitionId: string) => ["certificates", competitionId, "fonts"] as const,
  availability: (competitionId: string) =>
    ["certificates", competitionId, "me"] as const,
  mine: ["certificates", "mine"] as const,
  export: (competitionId: string, jobId: string) =>
    ["certificates", competitionId, "export", jobId] as const,
};

/** The bundled editor config (fonts, tokens, presets, geometry). Rarely changes
 *  (only when the deployment adds presets/fonts), so it's cached for a few
 *  minutes — long enough to be cheap, short enough that new presets/fonts show up
 *  without a hard reload. */
export function useCertificateManifest() {
  return useQuery({
    queryKey: certKeys.manifest,
    queryFn: () => certificateAssetsApi.manifest(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useCertificateTemplate(competitionId: string, enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: certKeys.template(competitionId),
    queryFn: () => certificatesApi.getTemplate(competitionId),
    enabled: isAuthenticated && enabled && Boolean(competitionId),
  });
}

export function useSaveCertificateTemplate(competitionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CertificateTemplateInput) =>
      certificatesApi.saveTemplate(competitionId, input),
    onSuccess: (data) => qc.setQueryData(certKeys.template(competitionId), data),
  });
}

export function useUploadCertificateBackground(competitionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => certificatesApi.uploadBackground(competitionId, file),
    onSuccess: (data) => {
      qc.setQueryData(certKeys.template(competitionId), data);
      // Force the canvas to reload the new bytes even when a background already
      // existed (the query would otherwise serve the stale cached blob).
      qc.invalidateQueries({
        queryKey: ["certificates", competitionId, "background-image"],
      });
    },
  });
}

export function useUploadCertificateImage(competitionId: string) {
  return useMutation({
    mutationFn: (file: File) => certificatesApi.uploadImage(competitionId, file),
  });
}

/** Render the in-progress design (real renderer, sample tokens) → PNG blob. */
export function usePreviewCertificate(competitionId: string) {
  return useMutation({
    mutationFn: (input: CertificateTemplateInput) =>
      certificatesApi.preview(competitionId, input),
  });
}

export function useReleaseCertificates(competitionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => certificatesApi.release(competitionId),
    onSuccess: (data) => {
      qc.setQueryData(certKeys.template(competitionId), data);
      qc.invalidateQueries({ queryKey: certKeys.availability(competitionId) });
      qc.invalidateQueries({ queryKey: certKeys.mine });
    },
  });
}

export function useCreateCertificateExport(competitionId: string) {
  return useMutation({
    mutationFn: () => certificatesApi.createExport(competitionId),
  });
}

/** Poll a bulk-export job until it finishes (done/failed). */
export function useCertificateExport(
  competitionId: string,
  jobId: string | null,
) {
  return useQuery({
    queryKey: certKeys.export(competitionId, jobId ?? ""),
    queryFn: () => certificatesApi.getExport(competitionId, jobId as string),
    enabled: Boolean(competitionId) && Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 2000 : false;
    },
  });
}

/** Whether the current user can download a certificate here (released + eligible). */
export function useMyCertificateAvailability(competitionId: string, enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: certKeys.availability(competitionId),
    queryFn: () => certificatesApi.myAvailability(competitionId),
    enabled: isAuthenticated && enabled && Boolean(competitionId),
  });
}

/** Every released certificate the user can download, across competitions. */
export function useMyCertificates() {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: certKeys.mine,
    queryFn: () => meCertificatesApi.list(),
    enabled: isAuthenticated,
  });
}

export function useDownloadMyCertificate(competitionId: string) {
  return useMutation({
    mutationFn: (filename: string) =>
      certificatesApi.downloadMine(competitionId, filename),
  });
}

/** The uploaded background as a Blob (editor canvas). Keyed on has-image so it
 *  refetches after an upload swaps the template. */
export function useCertificateBackgroundImage(
  competitionId: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["certificates", competitionId, "background-image"],
    queryFn: () => certificatesApi.backgroundImage(competitionId),
    enabled: Boolean(competitionId) && enabled,
    staleTime: 0,
  });
}

/** The competition's uploaded custom fonts (organiser-only). */
export function useCertificateFonts(competitionId: string, enabled = true) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: certKeys.fonts(competitionId),
    queryFn: () => certificatesApi.fonts(competitionId),
    enabled: isAuthenticated && enabled && Boolean(competitionId),
  });
}

export function useUploadCertificateFont(competitionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, name }: { file: File; name?: string }) =>
      certificatesApi.uploadFont(competitionId, file, name),
    onSuccess: () => qc.invalidateQueries({ queryKey: certKeys.fonts(competitionId) }),
  });
}

export function useDeleteCertificateFont(competitionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (fontId: string) => certificatesApi.deleteFont(competitionId, fontId),
    onSuccess: () => qc.invalidateQueries({ queryKey: certKeys.fonts(competitionId) }),
  });
}

/** Trigger a download of the design as a portable JSON document. */
export function useExportCertificateTemplate(competitionId: string) {
  return useMutation({
    mutationFn: (filename: string) =>
      certificatesApi.exportTemplate(competitionId, filename),
  });
}

/** Replace the current design with a previously-exported document. */
export function useImportCertificateTemplate(competitionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (doc: unknown) => certificatesApi.importTemplate(competitionId, doc),
    onSuccess: (data) => {
      qc.setQueryData(certKeys.template(competitionId), data);
      qc.invalidateQueries({ queryKey: certKeys.fonts(competitionId) });
      qc.invalidateQueries({
        queryKey: ["certificates", competitionId, "background-image"],
      });
    },
  });
}

/** Imperatively fetch a custom font's bytes (for the editor's @font-face). Lives
 *  in the hook module so components don't import the API client directly (§8). */
export function fetchCertificateFontBlob(competitionId: string, fontId: string) {
  return certificatesApi.fontFile(competitionId, fontId);
}

/** An element image (signature/sponsor) as a Blob, by storage key. */
export function useCertificateMedia(competitionId: string, key: string | null) {
  return useQuery({
    queryKey: ["certificates", competitionId, "media", key ?? ""],
    queryFn: () => certificatesApi.media(competitionId, key as string),
    enabled: Boolean(competitionId) && Boolean(key),
    staleTime: Infinity,
  });
}
