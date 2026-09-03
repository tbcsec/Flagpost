// Branding snapshot shared by the server layout and the client (no "use client"
// / no browser or Node APIs, so it is safe in both). It carries the fully
// resolved theme (an AppliedTheme) plus the three white-label fields the lockup
// and tab title need. Cached in the `fp:brand` cookie by the client and injected
// into the initial HTML by the server layout, so custom branding paints on the
// first frame instead of flashing the Flagpost defaults.

import {
  DEFAULT_PALETTE,
  DEFAULT_PLATFORM_NAME,
  type AppliedTheme,
  type PaletteMode,
} from "@/lib/theme";
import type { SiteSettings } from "@/lib/types";

// Underscore, not the `fp:` prefix the localStorage keys use — ":" is not a
// valid cookie-name character (RFC 6265 token).
export const BRAND_COOKIE = "fp_brand";

export interface BrandSnapshot {
  palette: string;
  mode: PaletteMode;
  // Accent overrides for a built-in palette (null when the default "signal"
  // accent lets the palette's own primary show through).
  primary?: string | null;
  primaryForeground?: string | null;
  ring?: string | null;
  // Full `--token` → "H S% L%" pack when a custom brand theme (#323) is active.
  vars?: Record<string, string>;
  // Already absolutized to the browser-facing API origin (or a relative path in
  // same-origin mode), so it drops straight into an <img src>.
  logoUrl: string | null;
  platformName: string;
  showWordmark: boolean;
}

/** The shipped defaults — used when there is no cookie and the cold-start fetch
 *  is unavailable, matching the server-rendered <html data-palette="harbor">. */
export const DEFAULT_BRAND: BrandSnapshot = {
  palette: DEFAULT_PALETTE,
  mode: "dark",
  logoUrl: null,
  platformName: DEFAULT_PLATFORM_NAME,
  showWordmark: true,
};

/** Build the snapshot from resolved settings. `logoUrl` must already be the
 *  browser-facing URL (client: post-`select`; server: absolutized before call). */
export function brandFromSettings(
  settings: Pick<SiteSettings, "platform_name" | "show_wordmark">,
  logoUrl: string | null,
  resolved: AppliedTheme,
): BrandSnapshot {
  return {
    palette: resolved.palette,
    mode: resolved.mode,
    primary: resolved.primary,
    primaryForeground: resolved.primaryForeground,
    ring: resolved.ring,
    vars: resolved.vars,
    logoUrl,
    platformName: settings.platform_name,
    showWordmark: settings.show_wordmark,
  };
}

export function serializeBrand(brand: BrandSnapshot): string {
  return JSON.stringify(brand);
}

/** Defensively parse the cookie value. Returns null on anything malformed (a
 *  bad or stale cookie must never break the server render — the caller falls
 *  back to the cold-start fetch or the shipped defaults). */
export function parseBrand(raw: string | null | undefined): BrandSnapshot | null {
  if (!raw) return null;
  let v: unknown;
  try {
    v = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof v !== "object" || v === null) return null;
  const o = v as Record<string, unknown>;
  if (
    typeof o.palette !== "string" ||
    (o.mode !== "dark" && o.mode !== "light") ||
    typeof o.platformName !== "string" ||
    typeof o.showWordmark !== "boolean" ||
    (o.logoUrl !== null && typeof o.logoUrl !== "string")
  ) {
    return null;
  }
  const vars =
    o.vars && typeof o.vars === "object"
      ? (o.vars as Record<string, string>)
      : undefined;
  return {
    palette: o.palette,
    mode: o.mode,
    primary: typeof o.primary === "string" ? o.primary : null,
    primaryForeground:
      typeof o.primaryForeground === "string" ? o.primaryForeground : null,
    ring: typeof o.ring === "string" ? o.ring : null,
    vars,
    logoUrl: (o.logoUrl as string | null) ?? null,
    platformName: o.platformName,
    showWordmark: o.showWordmark,
  };
}

/** The inline CSS custom-properties to set on `<html style>` — mirrors
 *  applyResolvedTheme's var writes so the server paint matches the client's. */
export function brandStyleVars(brand: BrandSnapshot): Record<string, string> {
  if (brand.vars) return { ...brand.vars };
  if (!brand.primary) return {}; // default "signal": palette's own primary shows
  return {
    "--primary": brand.primary,
    "--ring": brand.ring ?? brand.primary,
    "--primary-foreground": brand.primaryForeground ?? "0 0% 100%",
  };
}
