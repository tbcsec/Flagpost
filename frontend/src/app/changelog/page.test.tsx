import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import ChangelogPage from "@/app/changelog/page";
import { CHANGELOG } from "@/lib/changelog";

let mockAuthStatus: "loading" | "authenticated" | "anonymous" = "anonymous";

vi.mock("@/stores/auth", () => ({
  useAuthStore: (sel: (s: { status: string }) => unknown) =>
    sel({ status: mockAuthStatus }),
}));

vi.mock("@/lib/hooks/use-site-settings", () => ({
  useBrandSettings: () => ({
    platform_name: "Flagpost",
    logo_url: null,
    show_wordmark: true,
  }),
}));

// The authenticated branch renders the full shell; stub it so this test stays a
// unit test of the page (the shell has its own coverage).
vi.mock("@/components/app/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="shell">{children}</div>
  ),
}));

describe("ChangelogPage", () => {
  it("renders every release with its date badge and GitHub link", () => {
    renderWithIntl(<ChangelogPage />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Changelog" }),
    ).toBeInTheDocument();

    for (const release of CHANGELOG) {
      expect(
        screen.getByRole("heading", { level: 2, name: release.version }),
      ).toBeInTheDocument();
    }
    // Newest release's outbound link points at its GitHub release page…
    expect(
      screen.getByRole("link", {
        name: `View the ${CHANGELOG[0].version} release on GitHub`,
      }),
    ).toHaveAttribute(
      "href",
      `https://github.com/tbcsec/Flagpost/releases/tag/${CHANGELOG[0].version}`,
    );
    // …and dates render through the localized badge.
    expect(screen.getAllByText(/^Released /)).toHaveLength(CHANGELOG.length);
  });

  it("gives a signed-out reader standalone chrome with the footer", () => {
    renderWithIntl(<ChangelogPage />);
    // The muted footer link everywhere else leads here; on this page it still
    // renders (self-link is harmless) alongside the mandatory attribution.
    expect(screen.getByText("Powered by")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Changelog" })).toHaveAttribute(
      "href",
      "/changelog",
    );
  });

  it("keeps the app shell for an authenticated reader", () => {
    mockAuthStatus = "authenticated";
    renderWithIntl(<ChangelogPage />);
    expect(screen.getByTestId("shell")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 1, name: "Changelog" }),
    ).toBeInTheDocument();
    mockAuthStatus = "anonymous";
  });
});
