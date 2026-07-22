"use client";

// Applies the effective site theme to <html> on every page — public (login /
// register) and authenticated alike — so branding is consistent before there's
// a session (§9). Effective palette = the per-user override (topbar palette
// menu) ?? the admin's site-wide default; the accent is always the site-wide
// one (theming is site-wide, not per-user, ADR-0011).
//
// It also caches the resolved theme so the no-flash inline script in layout.tsx
// can paint the right surfaces on the next load before React hydrates.

import { useEffect } from "react";

import {
  FALLBACK_SETTINGS,
  SITE_THEME_CACHE_KEY,
  useSiteSettings,
} from "@/lib/hooks/use-site-settings";
import { applyResolvedTheme, resolveTheme } from "@/lib/theme";
import { useAuthStore } from "@/stores/auth";

export function ThemeApplier() {
  const { data } = useSiteSettings();
  const paletteOverride = useAuthStore((s) => s.paletteOverride);
  const hydratePaletteOverride = useAuthStore((s) => s.hydratePaletteOverride);

  // Restore the saved per-user palette override once on mount.
  useEffect(() => {
    hydratePaletteOverride();
  }, [hydratePaletteOverride]);

  const settings = data ?? FALLBACK_SETTINGS;
  const palette = paletteOverride ?? settings.default_palette;
  const accent = settings.accent;

  useEffect(() => {
    const resolved = resolveTheme({ palette, accent });
    applyResolvedTheme(document.documentElement, resolved);
    try {
      window.localStorage.setItem(SITE_THEME_CACHE_KEY, JSON.stringify(resolved));
    } catch {
      /* private mode — the no-flash cache just won't be available next load */
    }
  }, [palette, accent]);

  // The platform name brands the browser tab too (§9), not just the UI chrome.
  useEffect(() => {
    if (settings.platform_name) document.title = settings.platform_name;
  }, [settings.platform_name]);

  return null;
}
