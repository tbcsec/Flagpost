import { describe, expect, it } from "vitest";

import { negotiateLocale } from "./negotiate";

// First-visit locale selection (ADR-0029): the cookie wins in request.ts; this
// covers the Accept-Language fallback that runs before any cookie exists.
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

  it("skips unavailable languages for the next preference", () => {
    expect(negotiateLocale("fr, de;q=0.8", available)).toBe("de");
  });

  it("ignores q=0 (explicitly refused) languages", () => {
    expect(negotiateLocale("de;q=0, en;q=0.5", available)).toBe("en");
  });

  it("ignores wildcard ranges rather than picking arbitrarily", () => {
    expect(negotiateLocale("*", available)).toBeNull();
    expect(negotiateLocale("fr, *;q=0.5", available)).toBeNull();
  });

  it("returns null for no match, an empty header, and garbage", () => {
    expect(negotiateLocale("fr", available)).toBeNull();
    expect(negotiateLocale("", available)).toBeNull();
    expect(negotiateLocale(";;;q=,", available)).toBeNull();
  });
});
