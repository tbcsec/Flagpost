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

function clearBrandCookie() {
  document.cookie = `${BRAND_COOKIE}=; path=/; max-age=0`;
}

describe("ThemeApplier (#362)", () => {
  beforeEach(() => {
    clearBrandCookie();
    document.documentElement.dataset.palette = "server-painted";
    document.documentElement.dataset.mode = "dark";
  });

  it("applies the theme and writes the fp_brand cookie once real data arrives", () => {
    mockUseSiteSettings.mockReturnValue({
      data: CUSTOM_SETTINGS,
      isPlaceholderData: false,
    });
    render(<ThemeApplier />);
    expect(document.documentElement.dataset.palette).toBe("eclipse");
    const raw = document.cookie
      .split("; ")
      .find((c) => c.startsWith(`${BRAND_COOKIE}=`));
    expect(raw).toBeTruthy();
    const brand = JSON.parse(decodeURIComponent(raw!.split("=").slice(1).join("=")));
    expect(brand.platformName).toBe("Acme CTF");
    expect(brand.palette).toBe("eclipse");
    expect(brand.logoUrl).toBe("http://localhost:8000/api/site-settings/logo?v=1");
    expect(brand.showWordmark).toBe(false);
    expect(brand.primary).toBeTruthy(); // the custom hex accent resolved
  });

  it("applies nothing while data is placeholder — the server paint stands", () => {
    mockUseSiteSettings.mockReturnValue({
      data: { ...FALLBACK_SETTINGS },
      isPlaceholderData: true,
    });
    render(<ThemeApplier />);
    // Would have been rewritten to the fallback "harbor" if it applied.
    expect(document.documentElement.dataset.palette).toBe("server-painted");
    expect(document.cookie.includes(`${BRAND_COOKIE}=`)).toBe(false);
  });

  it("applies nothing while data is undefined (fetch in flight)", () => {
    mockUseSiteSettings.mockReturnValue({
      data: undefined,
      isPlaceholderData: false,
    });
    render(<ThemeApplier />);
    expect(document.documentElement.dataset.palette).toBe("server-painted");
    expect(document.cookie.includes(`${BRAND_COOKIE}=`)).toBe(false);
  });
});
