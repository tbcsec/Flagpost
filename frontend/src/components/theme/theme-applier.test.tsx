import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeApplier } from "@/components/theme/theme-applier";
import { BRAND_COOKIE } from "@/lib/brand";
import { FALLBACK_SETTINGS } from "@/lib/hooks/use-site-settings";

const mockUseSiteSettings = vi.fn();
vi.mock("@/lib/hooks/use-site-settings", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/hooks/use-site-settings")>();
  return {
    ...actual,
    useSiteSettings: () => mockUseSiteSettings(),
  };
});

const CUSTOM_SETTINGS = {
  ...FALLBACK_SETTINGS,
  platform_name: "Acme CTF",
  default_palette: "eclipse",
  // A preset id (not raw hex — the §9 token rule applies to this tree); it
  // resolves to a real override so `primary` is exercised all the same.
  accent: "ultraviolet",
  logo_url: "http://localhost:8000/api/site-settings/logo?v=1",
  show_wordmark: false,
};

function readBrandCookie(): Record<string, unknown> | null {
  const raw = document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${BRAND_COOKIE}=`));
  if (!raw) return null;
  return JSON.parse(decodeURIComponent(raw.split("=").slice(1).join("=")));
}

describe("ThemeApplier (#362)", () => {
  beforeEach(() => {
    document.cookie = `${BRAND_COOKIE}=; path=/; max-age=0`;
    document.documentElement.dataset.palette = "server-painted";
    document.documentElement.dataset.mode = "dark";
  });

  it("applies the theme and writes the fp_brand cookie once real data arrives", () => {
    mockUseSiteSettings.mockReturnValue({ data: CUSTOM_SETTINGS, isError: false });
    render(<ThemeApplier />);
    expect(document.documentElement.dataset.palette).toBe("eclipse");
    const brand = readBrandCookie();
    expect(brand).not.toBeNull();
    expect(brand!.platformName).toBe("Acme CTF");
    expect(brand!.palette).toBe("eclipse");
    // The cookie stores the backend-RELATIVE logo path (canonical form).
    expect(brand!.logoPath).toBe("/api/site-settings/logo?v=1");
    expect(brand!.showWordmark).toBe(false);
    expect(brand!.primary).toBeTruthy(); // the accent preset resolved
  });

  it("applies nothing while the fetch is pending — the server paint stands", () => {
    mockUseSiteSettings.mockReturnValue({ data: undefined, isError: false });
    render(<ThemeApplier />);
    expect(document.documentElement.dataset.palette).toBe("server-painted");
    expect(readBrandCookie()).toBeNull();
  });

  it("converges to the fallback theme on a fetch ERROR without caching it", () => {
    mockUseSiteSettings.mockReturnValue({ data: undefined, isError: true });
    render(<ThemeApplier />);
    // A stale server paint must not stand forever — fall back to the defaults
    // (and keep the palette menu responsive)…
    expect(document.documentElement.dataset.palette).toBe(
      FALLBACK_SETTINGS.default_palette,
    );
    // …but never bake the fallback into the cookie.
    expect(readBrandCookie()).toBeNull();
  });
});
