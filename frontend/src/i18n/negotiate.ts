// Minimal Accept-Language negotiation (RFC 9110 §12.5.4) for the first-visit
// default before any locale cookie exists. Dependency-free and pure so it's
// unit-testable outside a request context.

type Range = { tag: string; quality: number };

function parseRange(part: string): Range | null {
  const [tag, ...params] = part.trim().split(";");
  if (!tag) return null;
  let quality = 1;
  for (const param of params) {
    const [key, value] = param.trim().split("=");
    if (key === "q") {
      const parsed = Number.parseFloat(value);
      quality = Number.isNaN(parsed) ? 0 : parsed;
    }
  }
  return { tag: tag.trim().toLowerCase(), quality };
}

/**
 * Pick the best available locale for an Accept-Language header, or null when
 * nothing matches. Matching is case-insensitive and falls back from a regional
 * tag to its base language ("de-AT" matches an available "de", and vice versa
 * an available "pt-BR" matches a requested "pt").
 */
export function negotiateLocale<T extends string>(
  acceptLanguage: string,
  available: readonly T[],
): T | null {
  const ranges = acceptLanguage
    .split(",")
    .map(parseRange)
    .filter((r): r is Range => r !== null && r.tag !== "" && r.quality > 0)
    .sort((a, b) => b.quality - a.quality);

  for (const { tag } of ranges) {
    if (tag === "*") continue;
    const exact = available.find((l) => l.toLowerCase() === tag);
    if (exact) return exact;
    const base = tag.split("-")[0];
    const byBase = available.find((l) => {
      const lower = l.toLowerCase();
      return lower === base || lower.startsWith(`${base}-`);
    });
    if (byBase) return byBase;
  }
  return null;
}
