import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import LoginPage from "@/app/login/page";
import { renderWithIntl } from "@/test/intl";

// Smoke coverage for the i18n reference extraction (ADR-0029): every visible
// string now routes through auth.login.* messages, so a missing/renamed key
// renders as its raw key path and these English-text assertions fail. Hooks and
// navigation are mocked so the test drives pure rendering.
const mockUseSearchParams = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => mockUseSearchParams(),
}));

const mockUseAuthProviders = vi.fn();
vi.mock("@/lib/hooks/use-users", () => ({
  useLogin: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useAuthProviders: () => mockUseAuthProviders(),
}));

// Default (no mockReturnValue set) resolves to "no public pages", so the
// pre-existing cases render exactly as before this hook existed.
const mockUsePageNav = vi.fn();
vi.mock("@/lib/hooks/use-pages", () => ({
  usePageNav: () => mockUsePageNav() ?? { data: [] },
}));

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

function params(error: string | null) {
  return { get: (key: string) => (key === "error" ? error : null) };
}

function settings(
  overrides: Partial<{ demo_mode: boolean; demo_stock_credentials: boolean }> = {},
) {
  return {
    platform_name: "Flagpost",
    default_palette: "harbor",
    accent: "signal",
    registration_open: true,
    logo_url: null,
    show_wordmark: true,
    demo_mode: false,
    demo_stock_credentials: false,
    login_notice: null,
    archive_auto_delete: true,
    archive_retention_days: 30,
    email_required: false,
    ...overrides,
  };
}

describe("LoginPage", () => {
  it("renders the sign-in form with SSO buttons", () => {
    mockUseSearchParams.mockReturnValue(params(null));
    mockUseSiteSettings.mockReturnValue({ data: settings() });
    mockUseAuthProviders.mockReturnValue({
      data: [
        {
          slug: "company-sso",
          name: "Company SSO",
          kind: "oidc",
          brand: null,
          login_url: "http://localhost:8000/api/auth/oidc/company-sso/login",
        },
      ],
    });
    renderWithIntl(<LoginPage />);
    // "Sign in" is both the card title and the submit button — assert the
    // button by role and the title's sibling description by text.
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByText("Access your competitions.")).toBeInTheDocument();
    expect(screen.getByLabelText("Username or email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Sign in with Company SSO" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Register" })).toBeInTheDocument();
  });

  it("maps a known SSO error code to its message and unknown codes to the default", () => {
    mockUseSiteSettings.mockReturnValue({ data: settings() });
    mockUseAuthProviders.mockReturnValue({ data: [] });

    mockUseSearchParams.mockReturnValue(params("invalid_state"));
    const { unmount } = renderWithIntl(<LoginPage />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      /expired or was already used/,
    );
    unmount();

    mockUseSearchParams.mockReturnValue(params("no_such_code"));
    renderWithIntl(<LoginPage />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      /Single sign-on failed/,
    );
  });

  it("shows the demo accounts card only when stock credentials apply", () => {
    mockUseSearchParams.mockReturnValue(params(null));
    mockUseAuthProviders.mockReturnValue({ data: [] });

    mockUseSiteSettings.mockReturnValue({
      data: settings({ demo_mode: true, demo_stock_credentials: true }),
    });
    const { unmount } = renderWithIntl(<LoginPage />);
    expect(screen.getByText("Try it instantly")).toBeInTheDocument();
    expect(screen.getByText("Administrator")).toBeInTheDocument();
    // The rich-text message interleaves the <pw> mono span mid-sentence.
    expect(
      screen.getByText(/resets every hour, on the hour/),
    ).toBeInTheDocument();
    unmount();

    mockUseSiteSettings.mockReturnValue({
      data: settings({ demo_mode: false, demo_stock_credentials: false }),
    });
    renderWithIntl(<LoginPage />);
    expect(screen.queryByText("Try it instantly")).not.toBeInTheDocument();
  });

  it("hides the demo card when a custom baseline replaces the stock accounts (#357)", () => {
    // Demo mode is on (banner still shows) but a baseline is configured, so the
    // stock credentials no longer exist — the card must not advertise them.
    mockUseSearchParams.mockReturnValue(params(null));
    mockUseAuthProviders.mockReturnValue({ data: [] });
    mockUseSiteSettings.mockReturnValue({
      data: settings({ demo_mode: true, demo_stock_credentials: false }),
    });
    renderWithIntl(<LoginPage />);
    expect(screen.queryByText("Try it instantly")).not.toBeInTheDocument();
  });
});

describe("public page links (#198)", () => {
  it("renders a quiet link row for public pages", () => {
    mockUseSearchParams.mockReturnValue(params(null));
    mockUseSiteSettings.mockReturnValue({ data: settings() });
    mockUseAuthProviders.mockReturnValue({ data: [] });
    mockUsePageNav.mockReturnValue({
      data: [
        { slug: "about", title: "About this event", icon: "info", nav_order: 0 },
        { slug: "rules", title: "Rules", icon: "book", nav_order: 1 },
      ],
    });
    renderWithIntl(<LoginPage />);

    const nav = screen.getByRole("navigation", { name: "Site pages" });
    const links = Array.from(nav.querySelectorAll("a")).map((a) => ({
      href: a.getAttribute("href"),
      text: a.textContent,
    }));
    expect(links).toEqual([
      { href: "/p/about", text: "About this event" },
      { href: "/p/rules", text: "Rules" },
    ]);
  });

  it("renders no row when there are no public pages", () => {
    mockUseSearchParams.mockReturnValue(params(null));
    mockUseSiteSettings.mockReturnValue({ data: settings() });
    mockUseAuthProviders.mockReturnValue({ data: [] });
    mockUsePageNav.mockReturnValue({ data: [] });
    renderWithIntl(<LoginPage />);
    expect(
      screen.queryByRole("navigation", { name: "Site pages" }),
    ).toBeNull();
  });
});
