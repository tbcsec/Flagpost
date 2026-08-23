import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { UsernameCard } from "@/components/profile/username-card";
import type { User } from "@/lib/types";

// The card must hide the form and show a dated notice while the cooldown is
// active — submitting then would be a guaranteed 409.

const base: User = {
  id: "u-1",
  email: null,
  display_name: "ada",
  created_at: "2026-01-01T00:00:00Z",
  email_verified_at: null,
  avatar_updated_at: null,
  username_change_allowed_at: null,
};

let current: User = base;
vi.mock("@/stores/auth", () => ({
  useAuthStore: (sel: (s: { user: User }) => unknown) => sel({ user: current }),
}));
vi.mock("@/lib/hooks/use-users", () => ({
  useChangeUsername: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

describe("UsernameCard", () => {
  it("shows the change form when no cooldown is active", () => {
    current = { ...base, username_change_allowed_at: null };
    renderWithIntl(<UsernameCard />);
    expect(screen.getByLabelText("Username")).toHaveValue("ada");
    expect(screen.getByLabelText("Current password")).toBeInTheDocument();
  });

  it("hides the form and shows the dated notice during the cooldown", () => {
    const future = new Date(Date.now() + 20 * 864e5).toISOString();
    current = { ...base, username_change_allowed_at: future };
    renderWithIntl(<UsernameCard />);
    expect(screen.queryByLabelText("Username")).toBeNull();
    expect(screen.getByText(/change it again on/i)).toBeInTheDocument();
  });
});
