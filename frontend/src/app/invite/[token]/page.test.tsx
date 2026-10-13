import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import InviteLandingPage from "@/app/invite/[token]/page";
import type { InviteLinkResolved } from "@/lib/types";

const mockPush = vi.fn();
const mockJoin = vi.fn();
const mockToast = vi.fn();
let mockResolve: {
  data?: InviteLinkResolved;
  isLoading: boolean;
  isError: boolean;
} = { isLoading: false, isError: true };
let mockAuthStatus: "loading" | "authenticated" | "anonymous" = "anonymous";

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "tok123" }),
  useRouter: () => ({ push: mockPush, replace: mockPush }),
}));

vi.mock("@/lib/hooks/use-invite-links", () => ({
  useInviteLinkResolve: () => mockResolve,
  useJoinViaInviteLink: () => ({ mutate: mockJoin, isPending: false }),
}));

vi.mock("@/lib/hooks/use-site-settings", () => ({
  useBrandSettings: () => ({
    platform_name: "Flagpost",
    logo_url: null,
    show_wordmark: true,
    registration_open: true,
  }),
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: (sel: (s: { status: string }) => unknown) =>
    sel({ status: mockAuthStatus }),
}));

vi.mock("@/stores/toast", () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}));

// The real modal needs the checkbox dance; a stub surfaces onConfirm directly.
vi.mock("@/components/competitions/rules-accept-modal", () => ({
  RulesAcceptModal: ({
    open,
    onConfirm,
  }: {
    open: boolean;
    onConfirm: () => void;
  }) => (open ? <button onClick={onConfirm}>AcceptRulesStub</button> : null),
}));

afterEach(() => {
  mockPush.mockClear();
  mockJoin.mockReset();
  mockToast.mockClear();
  mockResolve = { isLoading: false, isError: true };
  mockAuthStatus = "anonymous";
});

function resolved(overrides: Partial<InviteLinkResolved> = {}): InviteLinkResolved {
  return {
    capability: "join",
    competition_id: "c1",
    competition_name: "Alpha CTF",
    competition_status: "running",
    participation_mode: "individual",
    actionable: true,
    requires_login: true,
    ...overrides,
  };
}

describe("InviteLandingPage", () => {
  it("shows the invalid state for a dead or unknown link", () => {
    renderWithIntl(<InviteLandingPage />);
    expect(screen.getByText("This link isn't available")).toBeInTheDocument();
    expect(screen.queryByText(/invited to/)).toBeNull();
  });

  it("sends an anonymous visitor to login/register carrying the token as next", () => {
    mockResolve = { data: resolved(), isLoading: false, isError: false };
    renderWithIntl(<InviteLandingPage />);
    expect(screen.getByText("You're invited to Alpha CTF")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in to join" })).toHaveAttribute(
      "href",
      "/login?next=%2Finvite%2Ftok123",
    );
    expect(
      screen.getByRole("link", { name: "Create an account" }),
    ).toHaveAttribute("href", "/register?next=%2Finvite%2Ftok123");
  });

  it("joins directly when authenticated and lands in the app", () => {
    mockAuthStatus = "authenticated";
    mockResolve = { data: resolved(), isLoading: false, isError: false };
    mockJoin.mockImplementation((_input, opts) =>
      opts.onSuccess({ id: "c1", name: "Alpha CTF" }),
    );
    renderWithIntl(<InviteLandingPage />);
    fireEvent.click(screen.getByRole("button", { name: "Join competition" }));
    expect(mockJoin.mock.calls[0][0]).toEqual({ accept_rules: false });
    expect(mockToast).toHaveBeenCalledWith("Welcome to Alpha CTF!");
    expect(mockPush).toHaveBeenCalledWith("/");
  });

  it("retries a rules-gate 403 with acceptance after the prompt", () => {
    mockAuthStatus = "authenticated";
    mockResolve = { data: resolved(), isLoading: false, isError: false };
    mockJoin.mockImplementationOnce((_input, opts) =>
      opts.onError({
        message: "rules",
        detail: {
          code: "rules_not_accepted",
          competition_id: "c1",
          rules: { type: "doc", content: [] },
        },
      }),
    );
    renderWithIntl(<InviteLandingPage />);
    fireEvent.click(screen.getByRole("button", { name: "Join competition" }));
    // The prompt appears instead of an error…
    fireEvent.click(screen.getByText("AcceptRulesStub"));
    // …and the retry carries acceptance.
    expect(mockJoin.mock.calls[1][0]).toEqual({ accept_rules: true });
  });

  it("explains an ended competition instead of offering the join", () => {
    mockAuthStatus = "authenticated";
    mockResolve = {
      data: resolved({ competition_status: "ended", actionable: false }),
      isLoading: false,
      isError: false,
    };
    renderWithIntl(<InviteLandingPage />);
    expect(
      screen.getByText(/can no longer be used to join/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join competition" })).toBeNull();
  });

  it("hands a view link off to the public board", () => {
    mockResolve = {
      data: resolved({ capability: "view", actionable: true, requires_login: false }),
      isLoading: false,
      isError: false,
    };
    renderWithIntl(<InviteLandingPage />);
    expect(screen.getByText("Alpha CTF")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "View the scoreboard" }),
    ).toHaveAttribute("href", "/public/c1");
    expect(screen.queryByText(/Sign in/)).toBeNull();
  });
});
