import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

const createMutate = vi.fn();
const updateMutate = vi.fn();
const removeMutate = vi.fn();

// A visible hint and a hidden one, as an editor's list returns them (#213).
vi.mock("@/lib/hooks/use-hints", () => ({
  useHints: () => ({
    data: [
      { id: "h1", challenge_id: "c1", cost: 50, revealed: true, body: "Visible one", hidden: false, release_at: null },
      { id: "h2", challenge_id: "c1", cost: 0, revealed: true, body: "Locked one", hidden: true, release_at: null },
    ],
  }),
  useCreateHint: () => ({ mutate: createMutate, isPending: false, isError: false }),
  useUpdateHint: () => ({ mutate: updateMutate, isPending: false, isError: false }),
  useDeleteHint: () => ({ mutate: removeMutate, isPending: false, isError: false }),
}));
vi.mock("@/components/ui/confirm", () => ({
  useConfirm: () => () => Promise.resolve(true),
}));

import { HintsSection } from "@/components/challenges/hints-section";

describe("HintsSection — hidden/scheduled hints (#213)", () => {
  it("badges a hidden hint and publishes it on click", () => {
    renderWithIntl(<HintsSection competitionId="c1" challengeId="ch1" />);
    // The hidden hint shows a "Hidden" badge and a Publish button; the visible
    // one has neither (exactly one Publish button on the page).
    expect(screen.getByText("Hidden")).toBeTruthy();
    const publish = screen.getByRole("button", { name: "Publish" });
    fireEvent.click(publish);
    expect(updateMutate).toHaveBeenCalledWith({
      hintId: "h2",
      patch: { hidden: false },
    });
  });

  it("reveals the schedule field only when 'hidden until released' is checked", () => {
    renderWithIntl(<HintsSection competitionId="c1" challengeId="ch1" />);
    expect(screen.queryByLabelText("Hint release time")).toBeNull();
    fireEvent.click(screen.getByLabelText("Hidden until released"));
    expect(screen.getByLabelText("Hint release time")).toBeTruthy();
  });
});
