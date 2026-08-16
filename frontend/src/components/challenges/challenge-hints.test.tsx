import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChallengeHints } from "@/components/challenges/challenge-hints";
import { renderWithIntl } from "@/test/intl";

// Smoke coverage for the challenges i18n extraction (ADR-0029) — the hint list's
// cost/free copy and reveal control must resolve from messages.
const mockUseHints = vi.fn();
vi.mock("@/lib/hooks/use-hints", () => ({
  useHints: () => mockUseHints(),
  useRevealHint: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
}));

describe("ChallengeHints", () => {
  it("renders a priced hint with its cost and a reveal button", () => {
    mockUseHints.mockReturnValue({
      data: [{ id: "h1", revealed: false, cost: 50, body: null }],
    });
    renderWithIntl(<ChallengeHints competitionId="c1" challengeId="ch1" />);
    expect(screen.getByText("Hints")).toBeInTheDocument();
    expect(screen.getByText("Costs 50 pts")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reveal" })).toBeInTheDocument();
  });

  it("labels a zero-cost hint as free", () => {
    mockUseHints.mockReturnValue({
      data: [{ id: "h2", revealed: false, cost: 0, body: null }],
    });
    renderWithIntl(<ChallengeHints competitionId="c1" challengeId="ch1" />);
    expect(screen.getByText("Free hint")).toBeInTheDocument();
  });

  it("shows the body once revealed", () => {
    mockUseHints.mockReturnValue({
      data: [{ id: "h3", revealed: true, cost: 50, body: "look at the header" }],
    });
    renderWithIntl(<ChallengeHints competitionId="c1" challengeId="ch1" />);
    expect(screen.getByText("look at the header")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reveal" })).not.toBeInTheDocument();
  });

  it("renders nothing when a challenge has no hints", () => {
    mockUseHints.mockReturnValue({ data: [] });
    const { container } = renderWithIntl(
      <ChallengeHints competitionId="c1" challengeId="ch1" />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
