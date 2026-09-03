// Branding snapshot shared by the server layout and the client (no "use client"
// / no browser or Node APIs, so it is safe in both). It carries the fully
// resolved theme (an AppliedTheme) plus the three white-label fields the lockup
// and tab title need. Cached in the `fp_brand` cookie by the client and injected
// into the initial HTML by the server layout, so custom branding paints on the
// first frame instead of flashing the Flagpost defaults (#362).
//
// SECURITY: the cookie is an unauthenticated, client-controlled input to the
// SERVER render — React serialises style-object values into the HTML `style`
// attribute verbatim (a value containing ";" becomes extra live declarations),
// so parseBrand enforces a strict grammar: only known theme tokens, only
// HSL-channel-triple values, only backend-relative logo paths. Anything else is
// rejected wholesale and the server falls back to the cold-start fetch.
//
// Scope: colours + logo + name + wordmark — the surfaces #362 flagged. The
// front-door animated background (background_style) deliberately isn't carried:
// it's a client-rendered canvas, not first-paint chrome. Adding a field later is
// a schema change — bump BRAND_VERSION so old cookies invalidate deliberately.

import {
  DEFAULT_PALETTE,
  DEFAULT_PLATFORM_NAME,
  THEME_TOKEN_VARS,
  appliedThemeVars,
  isKnownPalette,
  paletteMode,
  resolveTheme,
  type AppliedTheme,
} from "@/lib/theme";
import type { SiteSettings } from "@/lib/types";

// Underscore, not the `fp:` prefix the localStorage keys use — ":" is not a
// valid cookie-name character (RFC 6265 token).
export const BRAND_COOKIE = "fp_brand";

// Bump on any BrandSnapshot shape/semantics change: parseBrand rejects other
// versions, so every stale cookie self-heals through one cold-start fetch
// instead of painting under old semantics for up to a year.
export const BRAND_VERSION = 1;

export interface BrandSnapshot extends AppliedTheme {
  v: number;
  // Backend-RELATIVE logo path ("/api/..."), or null for the built-in mark.
  // Stored relative so one canonical form flows everywhere; the consumers
  // absolutize with the API origin at use (apiAssetUrl / the server layout).
  logoPath: string | null;
  platformName: string;
  showWordmark: boolean;
}

/** The shipped defaults — used when there is no cookie and the cold-start fetch
 *  is unavailable. Derived from the same resolver the client uses so it can
 *  never disagree with it. */
export const DEFAULT_BRAND: BrandSnapshot = {
  v: BRAND_VERSION,
  ...resolveTheme({ palette: DEFAULT_PALETTE, accent: "signal" }),
  logoPath: null,
  platformName: DEFAULT_PLATFORM_NAME,
  showWordmark: true,
};

/** Build the snapshot from resolved settings. `logoPath` must be the
 *  backend-relative path (see BrandSnapshot). */
export function brandFromSettings(
  settings: Pick<SiteSettings, "platform_name" | "show_wordmark">,
  logoPath: string | null,
  resolved: AppliedTheme,
): BrandSnapshot {
  return {
    v: BRAND_VERSION,
    ...resolved,
    logoPath,
    platformName: settings.platform_name,
    showWordmark: settings.show_wordmark,
  };
}

export function serializeBrand(brand: BrandSnapshot): string {
  return JSON.stringify(brand);
}

// "H S% L%" channel triples — the only value shape the theme layer emits, and
// the only one the server will serialise into the style attribute.
const CHANNELS = /^\d{1,3}(\.\d+)? \d{1,3}(\.\d+)?% \d{1,3}(\.\d+)?%$/;
// Palette/custom-theme ids are slugs (mirrors the backend's PALETTE_PATTERN).
const SLUG = /^[a-z][a-z0-9-]{1,31}$/;
const KNOWN_VARS = new Set<string>(THEME_TOKEN_VARS);
const MAX_NAME_LENGTH = 64; // mirrors the backend's platform_name cap
const MAX_LOGO_PATH_LENGTH = 300;

function channelsOrNull(v: unknown): string | null | undefined {
  if (v === null || v === undefined) return null;
  if (typeof v === "string" && CHANNELS.test(v)) return v;
  return undefined; // invalid → caller rejects the cookie
}

/** Defensively parse the cookie value. Returns null on ANYTHING malformed — a
 *  bad, stale, or tampered cookie must never reach the server render (the
 *  caller falls back to the cold-start fetch or the shipped defaults). */
export function parseBrand(raw: string | null | undefined): BrandSnapshot | null {
  if (!raw) return null;
  let v: unknown;
  try {
    v = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof v !== "object" || v === null || Array.isArray(v)) return null;
  const o = v as Record<string, unknown>;

  if (o.v !== BRAND_VERSION) return null;
  if (typeof o.palette !== "string" || !SLUG.test(o.palette)) return null;
  if (o.mode !== "dark" && o.mode !== "light") return null;
  if (typeof o.platformName !== "string" || o.platformName.length === 0 || o.platformName.length > MAX_NAME_LENGTH) {
    return null;
  }
  if (typeof o.showWordmark !== "boolean") return null;
  if (o.logoPath !== null && typeof o.logoPath !== "string") return null;
  if (
    typeof o.logoPath === "string" &&
    (!o.logoPath.startsWith("/") ||
      o.logoPath.startsWith("//") ||
      o.logoPath.length > MAX_LOGO_PATH_LENGTH)
  ) {
    return null;
  }

  const primary = channelsOrNull(o.primary);
  const primaryForeground = channelsOrNull(o.primaryForeground);
  const ring = channelsOrNull(o.ring);
  if (primary === undefined || primaryForeground === undefined || ring === undefined) {
    return null;
  }

  let vars: Record<string, string> | undefined;
  if (o.vars !== undefined && o.vars !== null) {
    if (typeof o.vars !== "object" || Array.isArray(o.vars)) return null;
    vars = {};
    for (const [key, val] of Object.entries(o.vars as Record<string, unknown>)) {
      // Only the known theme tokens, only channel-triple values — everything
      // else is treated as tampering and rejects the whole cookie.
      if (!KNOWN_VARS.has(key)) return null;
      if (typeof val !== "string" || !CHANNELS.test(val)) return null;
      vars[key] = val;
    }
  }

  // Coherence: a built-in palette must exist and carry its own mode (a renamed
  // or removed palette would otherwise paint no CSS block under a mismatched
  // mode); a custom-theme id is only valid with its vars pack along.
  if (!vars) {
    if (!isKnownPalette(o.palette) || paletteMode(o.palette) !== o.mode) return null;
  }

  return {
    v: BRAND_VERSION,
    palette: o.palette,
    mode: o.mode,
    primary,
    primaryForeground,
    ring,
    vars,
    logoPath: (o.logoPath as string | null) ?? null,
    platformName: o.platformName,
    showWordmark: o.showWordmark,
  };
}

/** The inline CSS custom-properties to set on `<html style>` — delegates to the
 *  theme layer's own mapping so the server paint can't drift from the client's
 *  applyResolvedTheme. */
export function brandStyleVars(brand: BrandSnapshot): Record<string, string> {
  return appliedThemeVars(brand);
}
