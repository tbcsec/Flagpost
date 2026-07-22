import { describe, expect, it } from "vitest";

import {
  accentForegroundChannels,
  applyTheme,
  hexToHslChannels,
  isCustomAccent,
  paletteMode,
  resolveAccentHex,
} from "@/lib/theme";

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
