import { describe, expect, it } from "vitest";

import {
  BRAND_VERSION,
  DEFAULT_BRAND,
  brandFromSettings,
  brandStyleVars,
  parseBrand,
  serializeBrand,
  type BrandSnapshot,
} from "@/lib/brand";
import { resolveTheme } from "@/lib/theme";

const CUSTOM: BrandSnapshot = {
  v: BRAND_VERSION,
  palette: "eclipse",
  mode: "dark",
  primary: "262 83% 58%",
  primaryForeground: "0 0% 100%",
  ring: "262 83% 58%",
  logoPath: "/api/site-settings/logo?v=1",
  platformName: "Acme CTF",
  showWordmark: false,
};

describe("brand snapshot", () => {
  it("round-trips through serialize/parse", () => {
    expect(parseBrand(serializeBrand(CUSTOM))).toEqual(CUSTOM);
    expect(parseBrand(serializeBrand(DEFAULT_BRAND))).toMatchObject({
      palette: DEFAULT_BRAND.palette,
      platformName: DEFAULT_BRAND.platformName,
      logoPath: null,
    });
  });

  it("round-trips a custom-theme vars pack", () => {
    const themed: BrandSnapshot = {
      ...CUSTOM,
      palette: "corporate-theme",
      primary: null,
      primaryForeground: null,
      ring: null,
      vars: { "--background": "220 20% 10%", "--primary": "10 80% 50%" },
    };
    expect(parseBrand(serializeBrand(themed))).toEqual(themed);
  });

  it("rejects malformed cookie values instead of throwing", () => {
    expect(parseBrand(null)).toBeNull();
    expect(parseBrand("")).toBeNull();
    expect(parseBrand("not json {{{")).toBeNull();
    expect(parseBrand('"a string"')).toBeNull();
    expect(parseBrand("[1,2]")).toBeNull();
    expect(parseBrand(JSON.stringify({ palette: "harbor" }))).toBeNull();
    expect(parseBrand(JSON.stringify({ ...CUSTOM, mode: "sepia" }))).toBeNull();
    expect(parseBrand(JSON.stringify({ ...CUSTOM, showWordmark: "yes" }))).toBeNull();
    expect(parseBrand(JSON.stringify({ ...CUSTOM, logoPath: 42 }))).toBeNull();
  });

  it("rejects other schema versions (deliberate invalidation on change)", () => {
    expect(parseBrand(JSON.stringify({ ...CUSTOM, v: 0 }))).toBeNull();
    expect(parseBrand(JSON.stringify({ ...CUSTOM, v: 2 }))).toBeNull();
    const noV = { ...CUSTOM } as Record<string, unknown>;
    delete noV.v;
    expect(parseBrand(JSON.stringify(noV))).toBeNull();
  });

  it("rejects style-injection attempts (the cookie feeds the SSR style attr)", () => {
    // Values must be HSL channel triples — a ";" would become extra live
    // declarations in the server-rendered style attribute.
    expect(
      parseBrand(
        JSON.stringify({ ...CUSTOM, primary: "0;display:none" }),
      ),
    ).toBeNull();
    expect(
      parseBrand(
        JSON.stringify({
          ...CUSTOM,
          vars: { "--primary": "0;background-image:url(//evil)" },
        }),
      ),
    ).toBeNull();
    // Only the known theme tokens may appear as vars keys.
    expect(
      parseBrand(
        JSON.stringify({ ...CUSTOM, vars: { "--x": "220 20% 10%" } }),
      ),
    ).toBeNull();
    // Arrays and non-string values are tampering, not vars.
    expect(parseBrand(JSON.stringify({ ...CUSTOM, vars: ["--primary"] }))).toBeNull();
    expect(
      parseBrand(JSON.stringify({ ...CUSTOM, vars: { "--primary": 5 } })),
    ).toBeNull();
  });

  it("rejects non-relative or oversized logo paths", () => {
    expect(
      parseBrand(JSON.stringify({ ...CUSTOM, logoPath: "http://evil/x.png" })),
    ).toBeNull();
    expect(
      parseBrand(JSON.stringify({ ...CUSTOM, logoPath: "//evil/x.png" })),
    ).toBeNull();
    expect(
      parseBrand(JSON.stringify({ ...CUSTOM, logoPath: `/${"a".repeat(400)}` })),
    ).toBeNull();
  });

  it("rejects incoherent palette/mode combos for built-ins", () => {
    // A removed/renamed palette without a vars pack would paint no CSS block.
    expect(
      parseBrand(JSON.stringify({ ...CUSTOM, palette: "no-such-palette" })),
    ).toBeNull();
    // A built-in palette must carry its own mode.
    expect(parseBrand(JSON.stringify({ ...CUSTOM, mode: "light" }))).toBeNull();
  });

  it("builds from settings + a resolved theme (accent override)", () => {
    const resolved = resolveTheme({ palette: "harbor", accent: "ultraviolet" });
    const brand = brandFromSettings(
      { platform_name: "Acme", show_wordmark: true },
      "/api/site-settings/logo?v=2",
      resolved,
    );
    expect(brand.v).toBe(BRAND_VERSION);
    expect(brand.palette).toBe("harbor");
    expect(brand.mode).toBe("dark");
    expect(brand.primary).not.toBeNull(); // the accent preset overrides
    expect(brand.logoPath).toBe("/api/site-settings/logo?v=2");
    // The built product must itself pass the strict parse.
    expect(parseBrand(serializeBrand(brand))).toEqual(brand);
  });

  it("styleVars delegate to the theme layer's mapping", () => {
    expect(brandStyleVars(CUSTOM)).toEqual({
      "--primary": "262 83% 58%",
      "--ring": "262 83% 58%",
      "--primary-foreground": "0 0% 100%",
    });
    // Default "signal" accent → no inline overrides (palette CSS governs).
    expect(brandStyleVars(DEFAULT_BRAND)).toEqual({});
    // Custom theme pack → the full vars map verbatim.
    expect(
      brandStyleVars({
        ...DEFAULT_BRAND,
        vars: { "--background": "220 20% 10%" },
      }),
    ).toEqual({ "--background": "220 20% 10%" });
  });
});
