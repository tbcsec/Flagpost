import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ForgotPasswordPage from "@/app/forgot-password/page";
import { renderWithIntl } from "@/test/intl";

// Smoke coverage for the i18n reference extraction (ADR-0029) — asserts the
// English source strings render, form and success state alike.
const mockUseForgotPassword = vi.fn();
vi.mock("@/lib/hooks/use-users", () => ({
  useForgotPassword: () => mockUseForgotPassword(),
}));

vi.mock("@/lib/hooks/use-site-settings", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/hooks/use-site-settings")
  >("@/lib/hooks/use-site-settings");
  return {
    ...actual,
    useSiteSettings: () => ({ data: undefined }),
  };
});

describe("ForgotPasswordPage", () => {
  it("renders the request form", () => {
    mockUseForgotPassword.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isSuccess: false,
    });
    renderWithIntl(<ForgotPasswordPage />);
    expect(screen.getByText("Reset your password")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Send reset link" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Back to sign in" }),
    ).toBeInTheDocument();
  });

  it("shows the no-account-disclosure confirmation after submitting", () => {
    mockUseForgotPassword.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isSuccess: true,
    });
    renderWithIntl(<ForgotPasswordPage />);
    // Rich message: the {email} value is interleaved in a styled span.
    expect(screen.getByText(/If an account exists for/)).toBeInTheDocument();
    expect(screen.getByText(/Check your inbox/)).toBeInTheDocument();
  });
});
