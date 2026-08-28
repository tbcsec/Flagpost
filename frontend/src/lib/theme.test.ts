import { describe, expect, it } from "vitest";

import {
  accentForegroundChannels,
  applyTheme,
  hexToHslChannels,
  isCustomAccent,
  paletteMode,
  resolveAccentHex,
  resolveTheme,
  THEME_TOKENS,
} from "@/lib/theme";
import type { CustomTheme } from "@/lib/theme";

describe("hexToHslChannels", () => {
  it("converts primaries to HSL channel triples", () => {
    expect(hexToHslChannels("#FF0000")).toBe("0 100% 50%");
    expect(hexToHslChannels("#00FF00")).toBe("120 100% 50%");
    expect(hexToHslChannels("#0000FF")).toBe("240 100% 50%");
  });
  it("handles greys (zero saturation) and is hash-optional", () => {
    expect(hexToHslChannels("#000000")).toBe("0 0% 0%");
    expect(hexToHslChannels("FFFFFF")).toBe("0 0% 100%");
  });
});

describe("accentForegroundChannels", () => {
  it("picks white text on a dark accent and ink on a bright one", () => {
    expect(accentForegroundChannels("#3B82F6")).toBe("0 0% 100%"); // blue → white
    expect(accentForegroundChannels("#E0A500")).toBe("222 47% 11%"); // gold → ink
  });
});

describe("resolveAccentHex", () => {
  it("returns null for the default 'signal' (no override)", () => {
    expect(resolveAccentHex("signal")).toBeNull();
  });
  it("resolves a preset id to its hex and passes custom hex through", () => {
    expect(resolveAccentHex("azure")).toBe("#3B82F6");
    expect(resolveAccentHex("#a855f7")).toBe("#A855F7");
  });
});

describe("isCustomAccent / paletteMode", () => {
  it("recognises a custom hex vs a preset id", () => {
    expect(isCustomAccent("#A855F7")).toBe(true);
    expect(isCustomAccent("azure")).toBe(false);
  });
  it("knows each palette's light/dark character", () => {
    expect(paletteMode("harbor")).toBe("dark");
    expect(paletteMode("daybreak")).toBe("light");
    expect(paletteMode("nonsense")).toBe("dark"); // safe fallback
  });
});

describe("applyTheme", () => {
  it("sets palette + mode and overrides accent channels for a preset", () => {
    const root = document.createElement("html");
    applyTheme(root, { palette: "daybreak", accent: "azure" });
    expect(root.dataset.palette).toBe("daybreak");
    expect(root.dataset.mode).toBe("light");
    expect(root.style.getPropertyValue("--primary")).toBe("217 91% 60%");
    expect(root.style.getPropertyValue("--ring")).toBe("217 91% 60%");
    expect(root.style.getPropertyValue("--primary-foreground")).toBe("0 0% 100%");
  });

  it("clears the accent override for the default 'signal'", () => {
    const root = document.createElement("html");
    root.style.setProperty("--primary", "1 2% 3%");
    applyTheme(root, { palette: "harbor", accent: "signal" });
    expect(root.dataset.mode).toBe("dark");
    expect(root.style.getPropertyValue("--primary")).toBe("");
  });

  it("falls back to the default palette for an unknown id", () => {
    const root = document.createElement("html");
    applyTheme(root, { palette: "bogus", accent: "signal" });
    expect(root.dataset.palette).toBe("harbor");
  });
});

describe("custom themes (#323)", () => {
  const CUSTOM: CustomTheme = {
    id: "acme",
    mode: "dark",
    tokens: Object.fromEntries(THEME_TOKENS.map((t) => [t, "#112233"])),
  };

  it("resolves a preset into a full token var map when it's the active palette", () => {
    const t = resolveTheme({ palette: "acme", accent: "signal", customTheme: CUSTOM });
    expect(t.palette).toBe("acme");
    expect(t.mode).toBe("dark");
    expect(t.primary).toBeNull(); // the theme owns primary; accent doesn't compose
    expect(Object.keys(t.vars ?? {})).toHaveLength(THEME_TOKENS.length);
    expect(t.vars?.["--background"]).toBe(hexToHslChannels("#112233"));
  });

  it("ignores the preset when a per-user override selects a built-in", () => {
    const t = resolveTheme({ palette: "eclipse", accent: "signal", customTheme: CUSTOM });
    expect(t.palette).toBe("eclipse");
    expect(t.vars).toBeUndefined();
  });

  it("carries a light theme's mode onto data-mode (drives native color-scheme)", () => {
    // globals.css keys `color-scheme` off `data-mode`, not the palette id, so a
    // light custom theme must set data-mode="light" or native controls (date
    // pickers, scrollbars, autofill) render dark on a light surface (#323 review).
    const root = document.createElement("html");
    const light: CustomTheme = { id: "corp", mode: "light", tokens: CUSTOM.tokens };
    applyTheme(root, { palette: "corp", accent: "signal", customTheme: light });
    expect(root.dataset.mode).toBe("light");
  });

  it("injects the token pack inline and clears it when switching to a built-in", () => {
    const root = document.createElement("html");
    applyTheme(root, { palette: "acme", accent: "signal", customTheme: CUSTOM });
    expect(root.dataset.palette).toBe("acme");
    expect(root.dataset.mode).toBe("dark");
    expect(root.style.getPropertyValue("--background")).toBe(hexToHslChannels("#112233"));
    expect(root.style.getPropertyValue("--primary")).toBe(hexToHslChannels("#112233"));
    // Switching to a built-in must remove every injected token var.
    applyTheme(root, { palette: "harbor", accent: "signal" });
    expect(root.style.getPropertyValue("--background")).toBe("");
    expect(root.style.getPropertyValue("--primary")).toBe("");
    expect(root.dataset.palette).toBe("harbor");
  });
});
