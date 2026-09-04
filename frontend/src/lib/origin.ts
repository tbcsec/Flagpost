// API origin resolution — the single source for "where is the backend?".
// A leaf module (no store/transport imports) so BOTH the client API layer
// (lib/api.ts) and server code (lib/server/branding.ts) share one rule and
// can't drift (#362 review).

// Baked at build time. Three shapes:
//  - absolute origin (dev default, demo images) — cross-origin API;
//  - **empty string** — same-origin mode: every request goes out relative
//    (`/api/...`) and resolves against the page's own origin, for deployments
//    behind a single-origin proxy (Caddy). The versioned release images bake
//    this, which is what makes one image reproducible on any host.
// `??` (not `||`) keeps the deliberate "" from falling back to localhost.
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Absolutize a backend-relative path (e.g. a logo URL) to the API origin, so an
 *  `<img src>` resolves against the backend, not the frontend host. */
export function apiAssetUrl(path: string): string {
  return `${API_URL}${path}`;
}

/** The inverse: reduce an absolutized asset URL back to its backend-relative
 *  path (used when persisting into the brand cookie, which stores canonical
 *  relative paths). Returns null for anything not under the API origin. */
export function apiAssetPath(url: string | null): string | null {
  if (!url) return null;
  if (url.startsWith("/") && !url.startsWith("//")) return url;
  if (API_URL && url.startsWith(`${API_URL}/`)) return url.slice(API_URL.length);
  return null;
}
