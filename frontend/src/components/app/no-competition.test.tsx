import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NoCompetition } from "@/components/app/no-competition";
import { renderWithIntl } from "@/test/intl";

// Smoke coverage for the app-shell i18n extraction (ADR-0029) — the empty
// state's role-aware copy and CTA must resolve from messages.
const mockHas = vi.fn();
vi.mock("@/lib/hooks/use-permissions", () => ({
  useAccess: () => ({ has: mockHas }),
}));

describe("NoCompetition", () => {
  it("offers a create CTA to a manager who can create competitions", () => {
    mockHas.mockImplementation((p: string) => p === "create_competition");
    renderWithIntl(<NoCompetition />);
    expect(screen.getByText("No competition loaded")).toBeInTheDocument();
    expect(screen.getByText(/Create one to open its challenges/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Manage competitions" }),
    ).toHaveAttribute("href", "/admin/competitions");
  });

  it("shows a reassuring message with no CTA to a competitor", () => {
    mockHas.mockReturnValue(false);
    renderWithIntl(<NoCompetition />);
    expect(screen.getByText(/Check back soon/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
