"use client";

// Applies the effective site theme to <html> on every page — public (login /
// register) and authenticated alike — so branding is consistent before there's
// a session (§9). Effective palette = the per-user override (topbar palette
// menu) ?? the admin's site-wide default; the accent is always the site-wide
// one (theming is site-wide, not per-user, ADR-0011).
//
// First paint is handled elsewhere (#362): the root layout server-renders the
// branding from the `fp_brand` cookie (or a cold-start backend fetch), so this
// component deliberately applies NOTHING until the real settings fetch
// resolves — applying the placeholder would repaint the defaults over the
// correct server-painted theme. Once real data (or an override change)
// arrives, it applies the resolved theme and rewrites the cookie, which is
// what keeps the server's next paint current — including immediately after an
// admin saves new appearance settings.

import { useEffect } from "react";

import { BRAND_COOKIE, brandFromSettings, serializeBrand } from "@/lib/brand";
import {
  FALLBACK_SETTINGS,
  useSiteSettings,
} from "@/lib/hooks/use-site-settings";
import { applyResolvedTheme, resolveTheme } from "@/lib/theme";
import { useAuthStore } from "@/stores/auth";

// Pre-#362 localStorage cache for the removed no-flash inline script; cleared
// once so stale themes don't linger in storage forever.
const LEGACY_THEME_CACHE_KEY = "fp:site-theme";

export function ThemeApplier() {
  const { data, isPlaceholderData } = useSiteSettings();
  const paletteOverride = useAuthStore((s) => s.paletteOverride);
  const hydratePaletteOverride = useAuthStore((s) => s.hydratePaletteOverride);

  // Restore the saved per-user palette override once on mount.
  useEffect(() => {
    hydratePaletteOverride();
    try {
      window.localStorage.removeItem(LEGACY_THEME_CACHE_KEY);
    } catch {
      /* private mode */
    }
  }, [hydratePaletteOverride]);

  const settings = data ?? FALLBACK_SETTINGS;
  const ready = data !== undefined && !isPlaceholderData;
  const palette = paletteOverride ?? settings.default_palette;
  const accent = settings.accent;
  // The active custom theme (#323), when default_palette names a preset. A
  // per-user palette override to a built-in still wins (its id won't match).
  const customTheme = settings.active_theme ?? null;

  useEffect(() => {
    if (!ready) return; // the server-painted branding stands until real data
    const resolved = resolveTheme({ palette, accent, customTheme });
    applyResolvedTheme(document.documentElement, resolved);
    // Refresh the per-browser brand cookie the server layout paints from
    // (#362). Includes the viewer's own palette override — the cookie is
    // per-client, so their next load first-paints their override too.
    // logo_url is already absolutized by the query's select.
    const cookie = serializeBrand(
      brandFromSettings(settings, settings.logo_url, resolved),
    );
    // A cookie near the 4KB cap would be dropped or truncated by the browser;
    // skip writing rather than persist something unparseable — the server then
    // falls back to the cold-start fetch, which is always correct.
    if (cookie.length <= 3800) {
      document.cookie = `${BRAND_COOKIE}=${encodeURIComponent(cookie)}; path=/; max-age=31536000; SameSite=Lax`;
    }
    // `settings` is deliberately not a dependency: only fields that change the
    // painted theme or the cookie snapshot should retrigger, and those are
    // covered below (the cookie's name/logo fields ride along whenever the
    // theme reapplies or real data first lands via `ready`).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, palette, accent, customTheme, settings.platform_name, settings.logo_url, settings.show_wordmark]);

  // The platform name brands the browser tab too (§9), not just the UI chrome.
  // Runs for placeholder data as well — it matches the server-rendered title,
  // and keeps the tab current after an admin renames without a reload.
  useEffect(() => {
    if (settings.platform_name) document.title = settings.platform_name;
  }, [settings.platform_name]);

  return null;
}
