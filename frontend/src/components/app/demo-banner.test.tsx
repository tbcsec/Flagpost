import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DemoBanner } from "@/components/app/demo-banner";
import { renderWithIntl } from "@/test/intl";

// Smoke coverage for the app-shell i18n extraction (ADR-0029) — the banner's
// rich <b> message must render and stay gated on demo_mode.
const mockUseSiteSettings = vi.fn();
vi.mock("@/lib/hooks/use-site-settings", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/hooks/use-site-settings")
  >("@/lib/hooks/use-site-settings");
  return { ...actual, useSiteSettings: () => mockUseSiteSettings() };
});

describe("DemoBanner", () => {
  it("renders the demo notice (with its bolded reset clause) in demo mode", () => {
    mockUseSiteSettings.mockReturnValue({ data: { demo_mode: true } });
    renderWithIntl(<DemoBanner />);
    expect(screen.getByText(/Demo instance/)).toBeInTheDocument();
    // The <b> chunk is a separate element mid-sentence.
    expect(screen.getByText(/resets every hour, on the hour/)).toBeInTheDocument();
  });

  it("renders nothing when not a demo instance", () => {
    mockUseSiteSettings.mockReturnValue({ data: { demo_mode: false } });
    const { container } = renderWithIntl(<DemoBanner />);
    expect(container).toBeEmptyDOMElement();
  });
});
