import { describe, expect, it } from "vitest";

import { negotiateLocale, resolveLocale } from "./negotiate";

// First-visit locale selection (ADR-0029): the cookie wins (resolveLocale,
// below); this covers the Accept-Language scoring that runs before any cookie
// exists. Each available locale is scored by its most specific matching range.
describe("negotiateLocale", () => {
  const available = ["en", "de", "pt-BR"] as const;

  it("matches an exact tag", () => {
    expect(negotiateLocale("de", available)).toBe("de");
  });

  it("is case-insensitive", () => {
    expect(negotiateLocale("DE", available)).toBe("de");
    expect(negotiateLocale("pt-br", available)).toBe("pt-BR");
  });

  it("falls back from a regional tag to its base language", () => {
    expect(negotiateLocale("de-AT", available)).toBe("de");
  });

  it("matches a base-language request to a regional locale", () => {
    expect(negotiateLocale("pt", available)).toBe("pt-BR");
  });

  it("honours q-value ordering, not header order", () => {
    expect(negotiateLocale("de;q=0.5, en;q=0.9", available)).toBe("en");
  });

  it("accepts an uppercase Q parameter (RFC 5234 literals are case-insensitive)", () => {
    expect(negotiateLocale("en;Q=0, de", available)).toBe("de");
  });

  it("skips unavailable languages for the next preference", () => {
    expect(negotiateLocale("fr, de;q=0.8", available)).toBe("de");
  });

  it("ignores q=0 (explicitly refused) languages", () => {
    expect(negotiateLocale("de;q=0, en;q=0.5", available)).toBe("en");
  });

  it("lets a specific q=0 veto a locale a broader range would match", () => {
    // "pt" alone would base-match pt-BR, but the client refused pt-BR by name:
    // weight 0 on the most specific range means "not acceptable", not "unranked".
    expect(negotiateLocale("pt, pt-BR;q=0", ["pt-BR"] as const)).toBeNull();
  });

  it("treats a lone wildcard as anything-goes and serves the first available", () => {
    expect(negotiateLocale("*", available)).toBe("en");
    expect(negotiateLocale("fr, *;q=0.5", available)).toBe("en");
  });

  it("lets a full-weight wildcard outrank an explicitly downranked language", () => {
    // "anything at 1.0, de specifically at 0.1" → serve en via *, not de.
    expect(negotiateLocale("*, de;q=0.1", ["en", "de"] as const)).toBe("en");
  });

  it("returns null for no match, an empty header, and garbage", () => {
    expect(negotiateLocale("fr", available)).toBeNull();
    expect(negotiateLocale("", available)).toBeNull();
    expect(negotiateLocale(";;;q=,", available)).toBeNull();
  });
});

// The resolution order that request.ts wires to next/headers — the ADR's
// central runtime promise: explicit cookie → Accept-Language → default.
describe("resolveLocale", () => {
  const available = ["en", "de"] as const;

  it("lets an explicit cookie choice beat the browser's Accept-Language", () => {
    expect(resolveLocale("de", "en", available, "en")).toBe("de");
  });

  it("falls through an unshipped cookie locale to negotiation", () => {
    expect(resolveLocale("fr", "de", available, "en")).toBe("de");
  });

  it("falls through a garbage cookie with no negotiable header to the default", () => {
    expect(resolveLocale("xx-junk", "", available, "en")).toBe("en");
  });

  it("negotiates when no cookie is set", () => {
    expect(resolveLocale(undefined, "de-AT", available, "en")).toBe("de");
  });
});
