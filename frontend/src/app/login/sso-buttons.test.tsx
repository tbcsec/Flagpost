import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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

function Probe() {
  const { data } = useAuthProviders();
  return (
    <ul>
      {data?.map((p) => (
        <li key={p.slug}>
          <a href={p.login_url}>Sign in with {p.name}</a>
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
          { slug: "company-sso", name: "Company SSO" },
          { slug: "github", name: "GitHub" },
        ],
      }),
    );

    render(<Probe />, { wrapper });

    const link = await screen.findByRole("link", { name: "Sign in with Company SSO" });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("/api/auth/oidc/company-sso/login"),
    );
    expect(
      screen.getByRole("link", { name: "Sign in with GitHub" }),
    ).toBeInTheDocument();
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
});
