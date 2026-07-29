"use client";

// One hook module per domain (ARCHITECTURE.md §8). Site-wide theme + branding
// (§9). The read is public (login/register brand themselves before there's a
// session); the update is Administrator-only (manage_site_settings).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiAssetUrl, siteSettingsApi } from "@/lib/api";
import {
  DEFAULT_ACCENT,
  DEFAULT_PALETTE,
  DEFAULT_PLATFORM_NAME,
} from "@/lib/theme";
import type {
  BackupDocument,
  OperationalSettingsUpdate,
  SiteSettings,
} from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const SITE_SETTINGS_KEY = ["site-settings"] as const;
// localStorage cache so the no-flash inline script (see layout) can apply the
// last-known theme before the query resolves on a fresh load.
export const SITE_THEME_CACHE_KEY = "fp:site-theme";

export const FALLBACK_SETTINGS: SiteSettings = {
  platform_name: DEFAULT_PLATFORM_NAME,
  default_palette: DEFAULT_PALETTE,
  accent: DEFAULT_ACCENT,
  registration_open: true,
  logo_url: null,
  show_wordmark: true,
  demo_mode: false,
  archive_auto_delete: true,
  archive_retention_days: 30,
  email_required: false,
  email_verification_enabled: false,
};

/** Rewrite the backend-relative `logo_url` to the API origin so an `<img src>`
 *  resolves against the backend (which may be a different host in dev/prod). */
function absolutizeLogo(s: SiteSettings): SiteSettings {
  return s.logo_url ? { ...s, logo_url: apiAssetUrl(s.logo_url) } : s;
}

/** The site theme/branding. Rarely changes, so it's cached long and served from
 *  any page (public included). Falls back to the shipped defaults until loaded. */
export function useSiteSettings() {
  return useQuery({
    queryKey: SITE_SETTINGS_KEY,
    queryFn: siteSettingsApi.get,
    select: absolutizeLogo,
    staleTime: 5 * 60_000,
  });
}

export function useUpdateSiteSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      platform_name: string;
      default_palette: string;
      accent: string;
      show_wordmark: boolean;
    }) => siteSettingsApi.update(input),
    // The admin response is a superset of the public shape (adds updated_at);
    // caching it directly keeps every branding field (logo_url, show_wordmark)
    // intact. `select` absolutizes logo_url on read.
    onSuccess: (data) => queryClient.setQueryData(SITE_SETTINGS_KEY, data),
  });
}

/** Upload a custom org logo (Admin → Appearance). */
export function useUploadLogo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => siteSettingsApi.uploadLogo(file),
    onSuccess: (data) => queryClient.setQueryData(SITE_SETTINGS_KEY, data),
  });
}

/** Clear the custom logo, reverting to the built-in Flagpost mark. */
export function useDeleteLogo() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => siteSettingsApi.deleteLogo(),
    onSuccess: (data) => queryClient.setQueryData(SITE_SETTINGS_KEY, data),
  });
}

// --- Platform export / import (Admin → Site settings) ---

/** The selectable export/import sections offered by the backend. */
export function useBackupSections() {
  const authed = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ["backup", "sections"],
    queryFn: siteSettingsApi.backupSections,
    enabled: authed,
    staleTime: Infinity,
  });
}

export function useExportBackup() {
  return useMutation({
    mutationFn: (sections: string[]) => siteSettingsApi.exportBackup(sections),
  });
}

export function useImportBackup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sections, payload }: { sections: string[]; payload: BackupDocument }) =>
      siteSettingsApi.importBackup(sections, payload),
    // An import can touch almost anything — drop cached server state so every
    // view refetches the newly-imported data.
    onSuccess: () => queryClient.invalidateQueries(),
  });
}

// --- Operational settings (Admin → Site settings): registration + SMTP.
// Admin-only reads/writes; a change to registration also refreshes the public
// site-settings so the login/register screen reflects it.

const OPERATIONAL_KEY = ["site-settings", "operational"] as const;

export function useOperationalSettings() {
  const authed = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: OPERATIONAL_KEY,
    queryFn: siteSettingsApi.operational,
    enabled: authed,
  });
}

export function useUpdateOperationalSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: OperationalSettingsUpdate) =>
      siteSettingsApi.updateOperational(input),
    onSuccess: (data) => {
      queryClient.setQueryData(OPERATIONAL_KEY, data);
      queryClient.invalidateQueries({ queryKey: SITE_SETTINGS_KEY });
    },
  });
}
