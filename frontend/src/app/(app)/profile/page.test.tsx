import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProfilePage from "@/app/(app)/profile/page";
import { renderWithIntl } from "@/test/intl";

// The page groups its cards into URL-driven tabs (#113). Mock navigation + the
// data hooks, and stub the child cards so this exercises the tab logic itself
// (which panel is active, and that switching drives `?tab=`) rather than each
// card's internals.
const push = vi.fn();
let searchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/profile",
  useSearchParams: () => searchParams,
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: (sel: (s: unknown) => unknown) =>
    sel({ user: { display_name: "ada", email: "ada@example.com", email_verified_at: "2026-01-01" } }),
}));

vi.mock("@/lib/hooks/use-site-settings", () => ({
  useSiteSettings: () => ({ data: { email_verification_enabled: false } }),
}));

vi.mock("@/lib/hooks/use-users", () => ({
  useChangePassword: () => ({ mutate: vi.fn(), isPending: false, isError: false, isSuccess: false, error: null }),
  useResendVerification: () => ({ mutate: vi.fn(), isPending: false, isSuccess: false }),
}));

// Stub the three domain cards — each just marks its presence.
vi.mock("@/components/profile/email-card", () => ({
  EmailCard: () => <div data-testid="email-card" />,
}));
vi.mock("@/components/profile/notification-preferences", () => ({
  NotificationPreferencesCard: () => <div data-testid="notifications-card" />,
}));
vi.mock("@/components/profile/api-tokens-card", () => ({
  MyApiTokensCard: () => <div data-testid="tokens-card" />,
}));
vi.mock("@/components/profile/certificates-card", () => ({
  MyCertificatesCard: () => <div data-testid="certificates-card" />,
}));

/** The wrapper div the panel content sits in — carries the `hidden` toggle. */
function panelOf(testid: string): HTMLElement {
  return screen.getByTestId(testid).parentElement as HTMLElement;
}

describe("ProfilePage tabs", () => {
  beforeEach(() => {
    push.mockClear();
    searchParams = new URLSearchParams();
  });

  it("renders the four tabs", () => {
    renderWithIntl(<ProfilePage />);
    expect(screen.getByRole("tab", { name: "Account" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "API tokens" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Certificates" })).toBeInTheDocument();
  });

  it("defaults to the Account tab when no ?tab= is set", () => {
    renderWithIntl(<ProfilePage />);
    expect(screen.getByRole("tab", { name: "Account" })).toHaveAttribute("aria-selected", "true");
    // Account panel (holds the email card) is shown; the tokens panel is hidden.
    expect(panelOf("email-card").className).not.toContain("hidden");
    expect(panelOf("tokens-card").className).toContain("hidden");
  });

  it("honours ?tab=tokens", () => {
    searchParams = new URLSearchParams("tab=tokens");
    renderWithIntl(<ProfilePage />);
    expect(screen.getByRole("tab", { name: "API tokens" })).toHaveAttribute("aria-selected", "true");
    expect(panelOf("tokens-card").className).not.toContain("hidden");
    expect(panelOf("email-card").className).toContain("hidden");
  });

  it("falls back to Account for a stale/unknown ?tab=", () => {
    searchParams = new URLSearchParams("tab=nonsense");
    renderWithIntl(<ProfilePage />);
    expect(screen.getByRole("tab", { name: "Account" })).toHaveAttribute("aria-selected", "true");
  });

  it("pushes ?tab= when a tab is clicked", () => {
    renderWithIntl(<ProfilePage />);
    fireEvent.click(screen.getByRole("tab", { name: "Notifications" }));
    expect(push).toHaveBeenCalledWith("/profile?tab=notifications", { scroll: false });
  });
});
