import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ResetPasswordPage from "@/app/reset-password/page";
import { renderWithIntl } from "@/test/intl";

// Smoke coverage for the i18n reference extraction (ADR-0029) — asserts the
// English source strings render for both the form and the missing-token state.
const mockUseSearchParams = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => mockUseSearchParams(),
}));

const mockUseResetPassword = vi.fn();
vi.mock("@/lib/hooks/use-users", () => ({
  useResetPassword: () => mockUseResetPassword(),
}));

vi.mock("@/lib/hooks/use-site-settings", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/hooks/use-site-settings")
  >("@/lib/hooks/use-site-settings");
  return {
    ...actual,
    useSiteSettings: () => ({ data: undefined }),
    useBrandSettings: () => actual.FALLBACK_SETTINGS,
  };
});

function params(token: string | null) {
  return { get: (key: string) => (key === "token" ? token : null) };
}

describe("ResetPasswordPage", () => {
  it("renders the new-password form when the link carries a token", () => {
    mockUseSearchParams.mockReturnValue(params("tok123"));
    mockUseResetPassword.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
    });
    renderWithIntl(<ResetPasswordPage />);
    expect(screen.getByText("Choose a new password")).toBeInTheDocument();
    expect(screen.getByLabelText("New password")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Set new password" }),
    ).toBeInTheDocument();
  });

  it("points a token-less link at forgot-password", () => {
    mockUseSearchParams.mockReturnValue(params(null));
    mockUseResetPassword.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
    });
    renderWithIntl(<ResetPasswordPage />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      /missing its reset token/,
    );
    // The rich <link> tag must survive translation as a working anchor.
    expect(
      screen.getByRole("link", { name: "forgot password" }),
    ).toHaveAttribute("href", "/forgot-password");
  });
});
