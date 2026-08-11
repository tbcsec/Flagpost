import { describe, expect, it } from "vitest";

import {
  BACKGROUND_IDS,
  isAnimatedBackground,
  parseHslChannels,
} from "@/lib/backgrounds";

const FALLBACK = { h: 213, s: 41, l: 11 };

describe("isAnimatedBackground", () => {
  it("is true for each shipped style", () => {
    for (const id of BACKGROUND_IDS) {
      expect(isAnimatedBackground(id)).toBe(true);
    }
  });

  it("is false for none and unknown values (the frontend is the allowlist)", () => {
    expect(isAnimatedBackground("none")).toBe(false);
    expect(isAnimatedBackground("")).toBe(false);
    expect(isAnimatedBackground("matrix")).toBe(false);
  });
});

describe("parseHslChannels", () => {
  it("parses a plain channel triple", () => {
    expect(parseHslChannels("213 41% 11%", FALLBACK)).toEqual({ h: 213, s: 41, l: 11 });
  });

  it("tolerates surrounding whitespace (getPropertyValue often pads)", () => {
    expect(parseHslChannels("  160 84% 39%  ", FALLBACK)).toEqual({ h: 160, s: 84, l: 39 });
  });

  it("parses decimal channels", () => {
    expect(parseHslChannels("28.5 9% 8.5%", FALLBACK)).toEqual({ h: 28.5, s: 9, l: 8.5 });
  });

  it("falls back on an empty or malformed value rather than throwing", () => {
    expect(parseHslChannels("", FALLBACK)).toEqual(FALLBACK);
    expect(parseHslChannels("not a colour", FALLBACK)).toEqual(FALLBACK);
    expect(parseHslChannels("#1F9E6B", FALLBACK)).toEqual(FALLBACK);
  });
});
