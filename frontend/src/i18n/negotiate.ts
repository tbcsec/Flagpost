// Locale selection for the first-visit default (ADR-0029): a minimal
// Accept-Language negotiation (RFC 9110 §12.4.2 / §12.5.4). Dependency-free
// and pure so it's unit-testable outside a request context.

type Range = { tag: string; quality: number; order: number };

function parseRanges(acceptLanguage: string): Range[] {
  return acceptLanguage
    .split(",")
    .map((part, order): Range | null => {
      const [tag, ...params] = part.trim().split(";");
      if (!tag.trim()) return null;
      let quality = 1;
      for (const param of params) {
        const [key, value] = param.trim().split("=");
        // "Q=" is as valid as "q=" — RFC 5234 ABNF literals are case-insensitive.
        if (key.trim().toLowerCase() === "q") {
          const parsed = Number.parseFloat(value);
          quality = Number.isNaN(parsed) ? 0 : parsed;
        }
      }
      return { tag: tag.trim().toLowerCase(), quality, order };
    })
    .filter((r): r is Range => r !== null);
}

// How specifically a range names a locale: exact tag > prefix relation
// ("de" ↔ "de-AT") > shared base language ("de-AT" ↔ "de-CH") > wildcard.
// 0 = no match. The prefix/base cases are deliberately bidirectional — an
// available "de" should satisfy a "de-AT" request and vice versa.
function specificity(rangeTag: string, locale: string): number {
  if (rangeTag === "*") return 1;
  const l = locale.toLowerCase();
  if (l === rangeTag) return 4;
  if (l.startsWith(`${rangeTag}-`) || rangeTag.startsWith(`${l}-`)) return 3;
  if (l.split("-")[0] === rangeTag.split("-")[0]) return 2;
  return 0;
}

/**
 * Pick the best available locale for an Accept-Language header, or null when
 * nothing (acceptable) matches. Each available locale is scored by its **most
 * specific** matching range, so:
 *
 * - `q=0` on the specific tag vetoes that locale (weight 0 means "not
 *   acceptable") even when a broader range would otherwise catch it;
 * - `*` genuinely matches anything, so it can outrank an explicitly
 *   downranked named language rather than being ignored.
 *
 * Ties break on header order, then on `available` order — so the caller's
 * first locale doubles as the "anything is fine" pick for a lone `*`.
 */
export function negotiateLocale<T extends string>(
  acceptLanguage: string,
  available: readonly T[],
): T | null {
  const ranges = parseRanges(acceptLanguage);
  let best: { locale: T; quality: number; order: number } | null = null;
  for (const locale of available) {
    let match: { spec: number; quality: number; order: number } | null = null;
    for (const r of ranges) {
      const spec = specificity(r.tag, locale);
      if (spec === 0) continue;
      if (
        !match ||
        spec > match.spec ||
        (spec === match.spec && r.quality > match.quality)
      ) {
        match = { spec, quality: r.quality, order: r.order };
      }
    }
    if (!match || match.quality <= 0) continue; // unmatched, or explicitly refused
    if (
      !best ||
      match.quality > best.quality ||
      (match.quality === best.quality && match.order < best.order)
    ) {
      best = { locale, quality: match.quality, order: match.order };
    }
  }
  return best?.locale ?? null;
}

/**
 * The full resolution order ADR-0029 promises: explicit cookie choice →
 * Accept-Language → the default. Pure (the caller supplies the available
 * list), so the precedence itself is testable; src/i18n/request.ts is a thin
 * wrapper over this.
 */
export function resolveLocale<T extends string>(
  cookieValue: string | undefined,
  acceptLanguage: string,
  available: readonly T[],
  fallback: T,
): T {
  const chosen = available.find((l) => l === cookieValue);
  if (chosen) return chosen;
  return negotiateLocale(acceptLanguage, available) ?? fallback;
}
