import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SsoBrandIcon } from "@/components/brand/sso-brand-icons";
import { useAuthProviders } from "@/lib/hooks/use-users";

// The hook is what turns the public provider list into something the login page
// can render: it absolutizes the login URL to the API origin, because the SSO
// flow is a full-page navigation to the *backend* and components can't import
// the API client (§8).

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

// Mirrors the login page's provider row: brand mark (null for unbranded)
// followed by the button text.
function Probe() {
  const { data } = useAuthProviders();
  return (
    <ul>
      {data?.map((p) => (
        <li key={p.slug}>
          <a href={p.login_url}>
            <SsoBrandIcon brand={p.brand} />
            Sign in with {p.name}
          </a>
        </li>
      ))}
    </ul>
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("useAuthProviders", () => {
  it("renders a button per enabled provider, pointing at the backend", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [
          { slug: "company-sso", name: "Company SSO", kind: "oidc" },
          { slug: "campus", name: "Campus IdP", kind: "saml" },
        ],
      }),
    );

    render(<Probe />, { wrapper });

    const link = await screen.findByRole("link", { name: "Sign in with Company SSO" });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("/api/auth/oidc/company-sso/login"),
    );
    // The login URL is kind-aware: a SAML provider points at its own transport.
    expect(
      screen.getByRole("link", { name: "Sign in with Campus IdP" }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining("/api/auth/saml/campus/login"),
    );
  });

  it("renders nothing when no providers are configured", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [] }),
    );

    render(<Probe />, { wrapper });

    await waitFor(() =>
      expect(screen.queryAllByRole("link")).toHaveLength(0),
    );
  });

  it("shows the brand mark on branded providers, none on the rest", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [
          { slug: "google", name: "Google", kind: "oidc", brand: "google" },
          { slug: "entra", name: "Microsoft", kind: "oidc", brand: "microsoft" },
          { slug: "company-sso", name: "Company SSO", kind: "oidc", brand: null },
        ],
      }),
    );

    render(<Probe />, { wrapper });

    // The lookups are by accessible name, which doubles as the "text unchanged"
    // assertion: the mark is aria-hidden, so the name stays "Sign in with X".
    const google = await screen.findByRole("link", { name: "Sign in with Google" });
    expect(google.querySelector('svg[data-brand-icon="google"]')).not.toBeNull();

    const microsoft = screen.getByRole("link", { name: "Sign in with Microsoft" });
    expect(
      microsoft.querySelector('svg[data-brand-icon="microsoft"]'),
    ).not.toBeNull();

    // Unbranded: no mark at all — the button renders exactly as before.
    const plain = screen.getByRole("link", { name: "Sign in with Company SSO" });
    expect(plain.querySelector("svg")).toBeNull();
    expect(plain).toHaveTextContent("Sign in with Company SSO");
  });
});
