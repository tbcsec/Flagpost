// Server-side branding resolution for the root layout (#362). Reads the
// `fp_brand` cookie the client keeps warm; on a cold start (no/invalid cookie —
// a first-ever visit or a cleared browser) falls back to fetching the public
// site-settings from the backend directly, so even the very first paint carries
// the operator's branding instead of flashing the Flagpost defaults.

import { cache } from "react";
import { cookies } from "next/headers";

import {
  DEFAULT_BRAND,
  BRAND_COOKIE,
  brandFromSettings,
  parseBrand,
  type BrandSnapshot,
} from "@/lib/brand";
import { API_URL } from "@/lib/origin";
import { DEFAULT_ACCENT, resolveTheme, type CustomTheme } from "@/lib/theme";

// Where the NEXT SERVER can reach the backend for the cold-start fetch. The
// browser-facing origin is often unusable here: in same-origin mode it's ""
// (relative URLs don't fetch server-side), and in the dev/prod compose stacks
// "localhost:8000" is the host's loopback, not the backend container. So a
// server-only INTERNAL_API_URL (e.g. http://backend:8000) takes precedence;
// unset, we try the public origin when it's absolute, else the dev default —
// and same-origin deployments without INTERNAL_API_URL skip the fetch outright
// (a guaranteed-doomed request is worse than the graceful default it yields).
const INTERNAL_API_URL = process.env.INTERNAL_API_URL || API_URL;

// Cross-request memo for the cold-start result. Cookie-less traffic is not
// rare (crawlers, uptime monitors, curl — none persist cookies), so without
// this every such request would cost a backend round-trip, and a backend
// outage would cost the full fetch timeout PER REQUEST. A short TTL bounds
// staleness (unlike the Next data cache, which was observed pinning a
// pre-setup response past its window — hence no `revalidate` here) while
// caching failures too, so an outage stalls one request per window, not all.
const MEMO_TTL_MS = 30_000;
let memo: { brand: BrandSnapshot | null; at: number } | null = null;

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
    accent: typeof s.accent === "string" ? s.accent : DEFAULT_ACCENT,
    customTheme: activeTheme,
  });
  return brandFromSettings(
    {
      platform_name: s.platform_name,
      show_wordmark: typeof s.show_wordmark === "boolean" ? s.show_wordmark : true,
    },
    typeof s.logo_url === "string" ? s.logo_url : null,
    resolved,
  );
}

async function fetchColdStartBrand(): Promise<BrandSnapshot | null> {
  if (!INTERNAL_API_URL) return null; // same-origin deploy without the env var
  const now = Date.now();
  if (memo && now - memo.at < MEMO_TTL_MS) return memo.brand;
  let brand: BrandSnapshot | null = null;
  try {
    // `no-store`: the Next data cache was observed pinning a pre-setup
    // "default branding" response past its revalidate window; the memo above
    // is the bounded cross-request cache instead.
    const res = await fetch(`${INTERNAL_API_URL}/api/site-settings`, {
      signal: AbortSignal.timeout(1500),
      cache: "no-store",
    });
    if (res.ok) brand = brandFromPublicSettings(await res.json());
  } catch (err) {
    // Backend down/slow — paint the shipped defaults, never block. Memoized
    // like a success so an outage doesn't stall every cookie-less request.
    console.warn("[branding] cold-start settings fetch failed:", err);
  }
  memo = { brand, at: now };
  return brand;
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
