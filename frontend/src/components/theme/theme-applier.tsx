"use client";

// Applies the effective site theme to <html> on every page — public (login /
// register) and authenticated alike — so branding is consistent before there's
// a session (§9). Effective palette = the per-user override (topbar palette
// menu) ?? the admin's site-wide default; the accent is always the site-wide
// one (theming is site-wide, not per-user, ADR-0011).
//
// First paint is handled elsewhere (#362): the root layout server-renders the
// branding from the `fp_brand` cookie (or a cold-start backend fetch), so this
// component applies NOTHING while the settings fetch is pending — applying the
// fallback would repaint the defaults over the correct server-painted theme.
// Once the fetch resolves it applies the resolved theme and rewrites the
// cookie, which keeps the server's next paint current (including immediately
// after an admin saves new appearance settings). If the fetch ERRORS, it
// applies the fallback so a stale server paint converges to the shipped
// defaults and the palette menu stays live — but never writes the cookie from
// fallback data.

import { useEffect } from "react";

import { BRAND_COOKIE, brandFromSettings, serializeBrand } from "@/lib/brand";
import { deleteCookie, setCookie } from "@/lib/cookies";
import {
  FALLBACK_SETTINGS,
  useSiteSettings,
} from "@/lib/hooks/use-site-settings";
import { apiAssetPath } from "@/lib/origin";
import { applyResolvedTheme, resolveTheme } from "@/lib/theme";
import { useAuthStore } from "@/stores/auth";

// Pre-#362 localStorage cache for the removed no-flash inline script; cleared
// so stale themes don't linger in storage. Sunset: remove this line once
// pre-#362 clients are unlikely to return (a release or two).
const LEGACY_THEME_CACHE_KEY = "fp:site-theme";

export function ThemeApplier() {
  const { data, isError } = useSiteSettings();
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

  // Pending (no data, no error): the server-painted branding stands untouched.
  const settings = data ?? (isError ? FALLBACK_SETTINGS : null);
  const palette = paletteOverride ?? settings?.default_palette;
  const accent = settings?.accent;
  // The active custom theme (#323), when default_palette names a preset. A
  // per-user palette override to a built-in still wins (its id won't match).
  const customTheme = settings?.active_theme ?? null;

  useEffect(() => {
    if (!settings || palette === undefined || accent === undefined) return;
    applyResolvedTheme(
      document.documentElement,
      resolveTheme({ palette, accent, customTheme }),
    );
  }, [settings, palette, accent, customTheme]);

  // Refresh the per-browser brand cookie the server layout paints from (#362)
  // — only from REAL data (caching the error-fallback would bake the defaults
  // into next load's first paint). Includes the viewer's own palette override:
  // the cookie is per-client, so their next load first-paints it too. The
  // cookie stores the backend-relative logo path (canonical form).
  useEffect(() => {
    if (!data) return;
    const resolved = resolveTheme({
      palette: paletteOverride ?? data.default_palette,
      accent: data.accent,
      customTheme: data.active_theme ?? null,
    });
    const cookie = serializeBrand(
      brandFromSettings(data, apiAssetPath(data.logo_url), resolved),
    );
    if (!setCookie(BRAND_COOKIE, cookie)) {
      // Oversized snapshot: a stale smaller cookie must not keep winning on
      // the server, so expire it — the cold-start fetch is always correct.
      deleteCookie(BRAND_COOKIE);
    }
  }, [data, paletteOverride]);

  // The platform name brands the browser tab too (§9) — from real data only,
  // so an errored fetch never stamps "Flagpost" over the server-painted title.
  useEffect(() => {
    if (data?.platform_name) document.title = data.platform_name;
  }, [data?.platform_name]);

  return null;
}
