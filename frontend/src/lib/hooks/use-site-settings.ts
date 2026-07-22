"use client";

// One hook module per domain (ARCHITECTURE.md §8). Site-wide theme + branding
// (§9). The read is public (login/register brand themselves before there's a
// session); the update is Administrator-only (manage_site_settings).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { siteSettingsApi } from "@/lib/api";
import {
  DEFAULT_ACCENT,
  DEFAULT_PALETTE,
  DEFAULT_PLATFORM_NAME,
} from "@/lib/theme";
import type { SiteSettings } from "@/lib/types";

const SITE_SETTINGS_KEY = ["site-settings"] as const;
// localStorage cache so the no-flash inline script (see layout) can apply the
// last-known theme before the query resolves on a fresh load.
export const SITE_THEME_CACHE_KEY = "fp:site-theme";

export const FALLBACK_SETTINGS: SiteSettings = {
  platform_name: DEFAULT_PLATFORM_NAME,
  default_palette: DEFAULT_PALETTE,
  accent: DEFAULT_ACCENT,
};

/** The site theme/branding. Rarely changes, so it's cached long and served from
 *  any page (public included). Falls back to the shipped defaults until loaded. */
export function useSiteSettings() {
  return useQuery({
    queryKey: SITE_SETTINGS_KEY,
    queryFn: siteSettingsApi.get,
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
    }) => siteSettingsApi.update(input),
    onSuccess: (data) => {
      queryClient.setQueryData(SITE_SETTINGS_KEY, {
        platform_name: data.platform_name,
        default_palette: data.default_palette,
        accent: data.accent,
      });
    },
  });
}
