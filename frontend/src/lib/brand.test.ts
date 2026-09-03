import { describe, expect, it } from "vitest";

import {
  DEFAULT_BRAND,
  brandFromSettings,
  brandStyleVars,
  parseBrand,
  serializeBrand,
  type BrandSnapshot,
} from "@/lib/brand";
import { resolveTheme } from "@/lib/theme";

const CUSTOM: BrandSnapshot = {
  palette: "midnight",
  mode: "dark",
  primary: "262 83% 58%",
  primaryForeground: "0 0% 100%",
  ring: "262 83% 58%",
  logoUrl: "http://localhost:8000/api/site-settings/logo?v=1",
  platformName: "Acme CTF",
  showWordmark: false,
};

describe("brand snapshot", () => {
  it("round-trips through serialize/parse", () => {
    expect(parseBrand(serializeBrand(CUSTOM))).toEqual(CUSTOM);
    expect(parseBrand(serializeBrand(DEFAULT_BRAND))).toMatchObject({
      palette: DEFAULT_BRAND.palette,
      platformName: DEFAULT_BRAND.platformName,
      logoUrl: null,
    });
  });

  it("rejects malformed cookie values instead of throwing", () => {
    expect(parseBrand(null)).toBeNull();
    expect(parseBrand("")).toBeNull();
    expect(parseBrand("not json {{{")).toBeNull();
    expect(parseBrand('"a string"')).toBeNull();
    expect(parseBrand("[1,2]")).toBeNull();
    // Missing required fields / wrong types.
    expect(parseBrand(JSON.stringify({ palette: "harbor" }))).toBeNull();
    expect(
      parseBrand(
        JSON.stringify({ ...CUSTOM, mode: "sepia" }),
      ),
    ).toBeNull();
    expect(
      parseBrand(JSON.stringify({ ...CUSTOM, showWordmark: "yes" })),
    ).toBeNull();
    expect(parseBrand(JSON.stringify({ ...CUSTOM, logoUrl: 42 }))).toBeNull();
  });

  it("builds from settings + a resolved theme (accent override)", () => {
    const resolved = resolveTheme({ palette: "harbor", accent: "#7C5CFF" });
    const brand = brandFromSettings(
      { platform_name: "Acme", show_wordmark: true },
      "/api/site-settings/logo?v=2",
      resolved,
    );
    expect(brand.palette).toBe("harbor");
    expect(brand.mode).toBe("dark");
    expect(brand.primary).not.toBeNull(); // custom hex accent overrides
    expect(brand.logoUrl).toBe("/api/site-settings/logo?v=2");
    expect(brand.platformName).toBe("Acme");
  });

  it("styleVars mirror applyResolvedTheme's writes", () => {
    // Custom accent → the primary/ring/foreground triple.
    expect(brandStyleVars(CUSTOM)).toEqual({
      "--primary": "262 83% 58%",
      "--ring": "262 83% 58%",
      "--primary-foreground": "0 0% 100%",
    });
    // Default "signal" accent → no inline overrides (palette CSS governs).
    expect(brandStyleVars(DEFAULT_BRAND)).toEqual({});
    // Custom theme pack → the full vars map verbatim.
    const themed: BrandSnapshot = {
      ...DEFAULT_BRAND,
      palette: "corporate",
      vars: { "--background": "220 20% 10%", "--primary": "10 80% 50%" },
    };
    expect(brandStyleVars(themed)).toEqual({
      "--background": "220 20% 10%",
      "--primary": "10 80% 50%",
    });
  });

  it("round-trips a custom-theme vars pack", () => {
    const themed: BrandSnapshot = {
      ...CUSTOM,
      primary: null,
      primaryForeground: null,
      ring: null,
      vars: { "--background": "220 20% 10%" },
    };
    expect(parseBrand(serializeBrand(themed))).toEqual(themed);
  });
});
