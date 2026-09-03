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
    useBrandSettings: () => mockUseSiteSettings().data ?? actual.FALLBACK_SETTINGS,
  };
});

function params(error: string | null) {
  return { get: (key: string) => (key === "error" ? error : null) };
}

function settings(
  overrides: Partial<{
    demo_mode: boolean;
    demo_credentials: {
      label: string;
      description: string;
      identifier: string;
      password: string;
    }[];
  }> = {},
) {
  return {
    platform_name: "Flagpost",
    default_palette: "harbor",
    accent: "signal",
    registration_open: true,
    logo_url: null,
    show_wordmark: true,
    demo_mode: false,
    demo_credentials: [],
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

  it("renders the demo card from the configured accounts (#360)", () => {
    mockUseSearchParams.mockReturnValue(params(null));
    mockUseAuthProviders.mockReturnValue({ data: [] });

    mockUseSiteSettings.mockReturnValue({
      data: settings({
        demo_mode: true,
        demo_credentials: [
          {
            label: "Acme Owner",
            description: "full control",
            identifier: "acme-owner",
            password: "pw-1234",
          },
        ],
      }),
    });
    const { unmount } = renderWithIntl(<LoginPage />);
    expect(screen.getByText("Try it instantly")).toBeInTheDocument();
    // Account label + identifier come from the data, not hardcoded strings.
    expect(screen.getByText("Acme Owner")).toBeInTheDocument();
    expect(screen.getByText("acme-owner")).toBeInTheDocument();
    // The old stock accounts are gone.
    expect(screen.queryByText("Administrator")).not.toBeInTheDocument();
    unmount();

    // No accounts configured → no card even in demo mode.
    mockUseSiteSettings.mockReturnValue({
      data: settings({ demo_mode: true, demo_credentials: [] }),
    });
    renderWithIntl(<LoginPage />);
    expect(screen.queryByText("Try it instantly")).not.toBeInTheDocument();
  });

  it("never renders the demo card off a demo instance (#360)", () => {
    // The public read blanks demo_credentials off demo mode, but be defensive:
    // even if a list arrived, demo_mode false must hide the card.
    mockUseSearchParams.mockReturnValue(params(null));
    mockUseAuthProviders.mockReturnValue({ data: [] });
    mockUseSiteSettings.mockReturnValue({
      data: settings({
        demo_mode: false,
        demo_credentials: [
          {
            label: "Acme Owner",
            description: "",
            identifier: "acme-owner",
            password: "pw-1234",
          },
        ],
      }),
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
