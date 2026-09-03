// Server-side branding resolution for the root layout (#362). Reads the
// `fp_brand` cookie the client keeps warm; on a cold start (no/invalid cookie —
// a first-ever visit or a cleared browser) falls back to fetching the public
// site-settings from the backend directly, so even the very first paint carries
// the operator's branding instead of flashing the Flagpost defaults.

import { cache } from "react";
import { cookies } from "next/headers";

import {
  BRAND_COOKIE,
  DEFAULT_BRAND,
  brandFromSettings,
  parseBrand,
  type BrandSnapshot,
} from "@/lib/brand";
import { resolveTheme, type CustomTheme } from "@/lib/theme";

// The browser-facing API origin — must mirror lib/api.ts exactly (`??` keeps
// the deliberate "" of same-origin mode). Used to absolutize the logo URL for
// the <img> the BROWSER loads; "" correctly yields a relative same-origin path.
const PUBLIC_API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Where the NEXT SERVER can reach the backend for the cold-start fetch. The
// browser-facing origin is often unusable here: in same-origin mode it's ""
// (relative URLs don't fetch server-side), and in the dev/prod compose stacks
// "localhost:8000" is the host's loopback, not the backend container. So a
// server-only INTERNAL_API_URL (e.g. http://backend:8000) takes precedence;
// unset, we try the public origin when it's absolute, else the dev default.
// A failed/slow fetch degrades gracefully to the shipped defaults.
const INTERNAL_API_URL =
  process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Defensive read of the public site-settings shape into a BrandSnapshot. */
function brandFromPublicSettings(body: unknown): BrandSnapshot | null {
  if (typeof body !== "object" || body === null) return null;
  const s = body as Record<string, unknown>;
  if (typeof s.platform_name !== "string" || typeof s.default_palette !== "string") {
    return null;
  }
  const activeTheme =
    s.active_theme && typeof s.active_theme === "object"
      ? (s.active_theme as CustomTheme)
      : null;
  const resolved = resolveTheme({
    palette: s.default_palette,
    accent: typeof s.accent === "string" ? s.accent : "signal",
    customTheme: activeTheme,
  });
  const rawLogo = typeof s.logo_url === "string" ? s.logo_url : null;
  return brandFromSettings(
    {
      platform_name: s.platform_name,
      show_wordmark: typeof s.show_wordmark === "boolean" ? s.show_wordmark : true,
    },
    rawLogo ? `${PUBLIC_API_URL}${rawLogo}` : null,
    resolved,
  );
}

async function fetchColdStartBrand(): Promise<BrandSnapshot | null> {
  try {
    // Deliberately uncached (`no-store`): the Next data cache was observed
    // pinning a pre-setup "default branding" response past its revalidate
    // window, which would cold-paint defaults on a freshly-configured install
    // indefinitely. Cookie-less renders are rare (one per new browser — every
    // later load carries the fp_brand cookie), the call is a fast in-network
    // hop capped at 1.5s, and React's cache() still dedupes it within a
    // request (layout + generateMetadata share one fetch).
    const res = await fetch(`${INTERNAL_API_URL}/api/site-settings`, {
      signal: AbortSignal.timeout(1500),
      cache: "no-store",
    });
    if (!res.ok) return null;
    return brandFromPublicSettings(await res.json());
  } catch (err) {
    console.warn("[branding] cold-start fetch failed:", err);
    return null; // backend down/slow — paint the shipped defaults, never block
  }
}

/** The branding to inject into the initial HTML. Cookie first (per-browser,
 *  includes the viewer's own palette override, kept warm by ThemeApplier);
 *  cold-start backend fetch second; shipped defaults last. `cache()` dedupes
 *  the work across generateMetadata + the layout within one request. */
export const getServerBrand = cache(async (): Promise<BrandSnapshot> => {
  const jar = await cookies();
  const fromCookie = parseBrand(jar.get(BRAND_COOKIE)?.value);
  if (fromCookie) return fromCookie;
  return (await fetchColdStartBrand()) ?? DEFAULT_BRAND;
});
