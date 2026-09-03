import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RegisterPage from "@/app/register/page";
import { renderWithIntl } from "@/test/intl";

// The register page reads email_required off the public site-settings hook to
// decide whether the email field is mandatory (#56) — mock it plus the other
// domain hooks/router so the test drives pure rendering behaviour.
const mockUseSiteSettings = vi.fn();
vi.mock("@/lib/hooks/use-site-settings", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/hooks/use-site-settings")
  >("@/lib/hooks/use-site-settings");
  return {
    ...actual,
    useSiteSettings: () => mockUseSiteSettings(),
  };
});
vi.mock("@/lib/hooks/use-users", () => ({
  useRegister: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

function settings(overrides: Partial<{ email_required: boolean }> = {}) {
  return {
    platform_name: "Flagpost",
    default_palette: "harbor",
    accent: "signal",
    registration_open: true,
    logo_url: null,
    show_wordmark: true,
    demo_mode: false,
    demo_credentials: [],
    archive_auto_delete: true,
    archive_retention_days: 30,
    email_required: false,
    ...overrides,
  };
}

describe("RegisterPage", () => {
  it("renders email as optional when the allowlist is disabled", () => {
    mockUseSiteSettings.mockReturnValue({ data: settings({ email_required: false }) });
    renderWithIntl(<RegisterPage />);
    const email = screen.getByLabelText("Email (optional)") as HTMLInputElement;
    expect(email.required).toBe(false);
    expect(screen.getByText(/Optional — you can also sign in/)).toBeInTheDocument();
  });

  it("renders email as required when the allowlist is enabled", () => {
    mockUseSiteSettings.mockReturnValue({ data: settings({ email_required: true }) });
    renderWithIntl(<RegisterPage />);
    const email = screen.getByLabelText("Email") as HTMLInputElement;
    expect(email.required).toBe(true);
    expect(screen.getByText(/Required to register/)).toBeInTheDocument();
  });
});
