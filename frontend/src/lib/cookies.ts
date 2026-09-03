// Client-side cookie writers shared by the locale picker and the brand cache
// (#362) — one place for attributes, so a future change (Secure, domain scope)
// can't land in one writer and miss the other.

const ONE_YEAR_S = 60 * 60 * 24 * 365;
// Browsers cap a cookie at 4096 bytes of name+value (post-encoding) and
// silently drop larger writes — reject before that with margin.
const MAX_COOKIE_BYTES = 4000;

function attributes(maxAgeSeconds: number): string {
  // Secure on HTTPS deployments; omitted on plain-HTTP dev so the cookie still
  // sticks there. SameSite=Lax matches the pre-existing locale cookie.
  const secure =
    typeof location !== "undefined" && location.protocol === "https:"
      ? "; Secure"
      : "";
  return `; path=/; max-age=${maxAgeSeconds}; SameSite=Lax${secure}`;
}

/** Write a year-lived cookie. Returns false (writing nothing) when the ENCODED
 *  name+value would exceed the browser cap — callers decide how to degrade. */
export function setCookie(name: string, value: string): boolean {
  const encoded = encodeURIComponent(value);
  if (name.length + 1 + encoded.length > MAX_COOKIE_BYTES) return false;
  document.cookie = `${name}=${encoded}${attributes(ONE_YEAR_S)}`;
  return true;
}

/** Expire a cookie immediately. */
export function deleteCookie(name: string): void {
  document.cookie = `${name}=${attributes(0)}`;
}
