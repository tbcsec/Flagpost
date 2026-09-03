"use client";

// One hook module per domain (ARCHITECTURE.md §8). Site-wide theme + branding
// (§9). The read is public (login/register brand themselves before there's a
// session); the update is Administrator-only (manage_site_settings).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useInitialBrand } from "@/components/theme/brand-context";
import { apiAssetUrl, siteSettingsApi } from "@/lib/api";
import {
  DEFAULT_ACCENT,
  DEFAULT_PALETTE,
  DEFAULT_PLATFORM_NAME,
} from "@/lib/theme";
import type {
  BackupDocument,
  DemoCredential,
  OperationalSettingsUpdate,
  RichTextDoc,
  SiteSettings,
} from "@/lib/types";
import { useAuthStore } from "@/stores/auth";

const SITE_SETTINGS_KEY = ["site-settings"] as const;

export const FALLBACK_SETTINGS: SiteSettings = {
  platform_name: DEFAULT_PLATFORM_NAME,
  default_palette: DEFAULT_PALETTE,
  accent: DEFAULT_ACCENT,
  active_theme: null,
  background_style: "none",
  login_notice: null,
  registration_open: true,
  logo_url: null,
  show_wordmark: true,
  demo_mode: false,
  demo_credentials: [],
  archive_auto_delete: true,
  archive_retention_days: 30,
  email_required: false,
  email_verification_enabled: false,
  username_changes_enabled: true,
};

/** Rewrite the backend-relative `logo_url` to the API origin so an `<img src>`
 *  resolves against the backend (which may be a different host in dev/prod).
 *  Idempotent: the brand-placeholder settings (#362) already carry an absolute
 *  URL, and `select` runs over placeholder data too. */
function absolutizeLogo(s: SiteSettings): SiteSettings {
  if (!s.logo_url || s.logo_url.startsWith("http")) return s;
  return { ...s, logo_url: apiAssetUrl(s.logo_url) };
}

/** The site theme/branding. Rarely changes, so it's cached long and served from
 *  any page (public included). Until loaded, the placeholder is the shipped
 *  defaults overlaid with the server-injected brand snapshot (#362) — cookie or
 *  cold-start fetch — so the lockup/name never paint the Flagpost defaults on a
 *  branded instance. Consumers can keep the `data ?? FALLBACK_SETTINGS` idiom;
 *  the placeholder simply makes `data` branded from the first render. */
export function useSiteSettings() {
  const brand = useInitialBrand();
  return useQuery({
    queryKey: SITE_SETTINGS_KEY,
    queryFn: siteSettingsApi.get,
    select: absolutizeLogo,
    staleTime: 5 * 60_000,
    placeholderData: {
      ...FALLBACK_SETTINGS,
      platform_name: brand.platformName,
      logo_url: brand.logoUrl,
      show_wordmark: brand.showWordmark,
      // The RESOLVED palette (may be the viewer's own override or a custom
      // theme id) — display-equivalent for a placeholder. ThemeApplier never
      // applies placeholder data (it skips until the real fetch resolves), so
      // this can't repaint anything; the server HTML already painted it.
      default_palette: brand.palette,
    },
  });
}

export function useUpdateSiteSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      platform_name: string;
      default_palette: string;
      accent: string;
      background_style: string;
      // null clears the sign-in notice (#197); the form always sends it.
      login_notice: RichTextDoc | null;
      show_wordmark: boolean;
      // Demo login accounts (#360). Omitted = leave unchanged; only sent on a
      // demo instance (the editor is hidden otherwise).
      demo_credentials?: DemoCredential[];
    }) => siteSettingsApi.update(input),
    // The admin response is a superset of the public shape (adds updated_at);
    // caching it directly keeps every branding field (logo_url, show_wordmark)
    // intact. `select` absolutizes logo_url on read.
    onSuccess: (data) => queryClient.setQueryData(SITE_SETTINGS_KEY, data),
  });
}

/** Upload a custom org logo (Admin → Site settings → Appearance). */
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

/** Admin-only operational settings. `enabled` exists because the update notice
 *  (#111) mounts in the app shell for *everyone*: without a permission gate here
 *  every competitor would fire a request at an admin endpoint and take a 403 on
 *  each page load. Callers that already know the viewer is an admin can omit it. */
export function useOperationalSettings(enabled = true) {
  const authed = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: OPERATIONAL_KEY,
    queryFn: siteSettingsApi.operational,
    enabled: authed && enabled,
  });
}

/** Dismiss the update notice (#111). Writes the response straight into the
 *  operational-settings cache, so the banner disappears without a refetch. */
export function useDismissUpdateNotice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: siteSettingsApi.dismissUpdateNotice,
    onSuccess: (data) => queryClient.setQueryData(OPERATIONAL_KEY, data),
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
