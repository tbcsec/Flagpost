import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import VerifyEmailPage from "@/app/verify-email/page";
import { renderWithIntl } from "@/test/intl";

// The page reads the token off the query string and drives useVerifyEmail;
// mock both plus the site-settings brand hook so the test exercises pure
// rendering behaviour across the pending/success/error/missing-token states.
const mockUseSearchParams = vi.fn();
vi.mock("next/navigation", () => ({
  useSearchParams: () => mockUseSearchParams(),
  // The page mounts LocaleSwitcher, which reads the router now that >1 locale
  // ships (ADR-0029); refresh() only fires on a language change, never at render.
  useRouter: () => ({ refresh: () => {} }),
}));

const mockMutate = vi.fn();
const mockUseVerifyEmail = vi.fn();
vi.mock("@/lib/hooks/use-users", () => ({
  useVerifyEmail: () => mockUseVerifyEmail(),
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

function params(token: string | null) {
  return { get: (key: string) => (key === "token" ? token : null) };
}

function mutationState(
  overrides: Partial<{
    isPending: boolean;
    isIdle: boolean;
    isSuccess: boolean;
    isError: boolean;
    error: Error | null;
  }> = {},
) {
  return {
    mutate: mockMutate,
    isPending: false,
    isIdle: true,
    isSuccess: false,
    isError: false,
    error: null,
    ...overrides,
  };
}

describe("VerifyEmailPage", () => {
  it("shows an error when the link has no token", () => {
    mockUseSearchParams.mockReturnValue(params(null));
    mockUseVerifyEmail.mockReturnValue(mutationState());
    renderWithIntl(<VerifyEmailPage />);
    expect(screen.getByText(/missing its verification token/i)).toBeInTheDocument();
    expect(mockMutate).not.toHaveBeenCalled();
  });

  it("fires the verify mutation once for a present token", () => {
    mockUseSearchParams.mockReturnValue(params("abc123"));
    mockUseVerifyEmail.mockReturnValue(mutationState({ isIdle: false, isPending: true }));
    renderWithIntl(<VerifyEmailPage />);
    expect(mockMutate).toHaveBeenCalledTimes(1);
    expect(mockMutate).toHaveBeenCalledWith({ token: "abc123" });
    expect(screen.getByText(/verifying/i)).toBeInTheDocument();
  });

  it("shows a success message once verified", () => {
    mockUseSearchParams.mockReturnValue(params("abc123"));
    mockUseVerifyEmail.mockReturnValue(
      mutationState({ isIdle: false, isSuccess: true }),
    );
    renderWithIntl(<VerifyEmailPage />);
    expect(screen.getByText(/your email is verified/i)).toBeInTheDocument();
  });

  it("shows the server's error message when verification fails", () => {
    mockUseSearchParams.mockReturnValue(params("bad-token"));
    mockUseVerifyEmail.mockReturnValue(
      mutationState({
        isIdle: false,
        isError: true,
        error: new Error("This verification link is invalid or has expired"),
      }),
    );
    renderWithIntl(<VerifyEmailPage />);
    expect(screen.getByText(/invalid or has expired/i)).toBeInTheDocument();
  });
});
