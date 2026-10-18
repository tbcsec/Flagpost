import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JoinCompetitionPanel } from "@/components/competitions/join-competition-panel";
import type { Competition } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";

// The panel a member of another competition sees on one they haven't joined (#478).

const start = vi.fn();
vi.mock("@/components/competitions/use-public-join", () => ({
  usePublicJoin: () => ({ start, isPending: false, dialogs: null }),
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

function competition(overrides: Partial<Competition> = {}): Competition {
  return {
    id: "c2",
    name: "Autumn CTF",
    participation_mode: "individual",
    visibility: "public",
    archived_at: null,
    ...overrides,
  } as Competition;
}

beforeEach(() => start.mockReset());

describe("JoinCompetitionPanel", () => {
  it("offers the self-serve join for an open public competition", () => {
    renderWithIntl(<JoinCompetitionPanel competition={competition()} />);
    expect(screen.getByText("Autumn CTF")).toBeInTheDocument();
    expect(screen.getByText("You haven't joined this competition")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Join competition" }));
    expect(start).toHaveBeenCalledWith("c2", "Autumn CTF");
    expect(screen.getByRole("link", { name: "Browse competitions" })).toHaveAttribute(
      "href",
      "/lobby",
    );
  });

  it("doesn't offer a self-serve join for a private competition", () => {
    renderWithIntl(<JoinCompetitionPanel competition={competition({ visibility: "private" })} />);
    expect(screen.queryByRole("button", { name: "Join competition" })).toBeNull();
  });

  it("points an archived competition to the lobby instead", () => {
    renderWithIntl(
      <JoinCompetitionPanel competition={competition({ archived_at: "2026-10-01T00:00:00Z" })} />,
    );
    expect(screen.getByText("This competition isn't open to new competitors")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join competition" })).toBeNull();
    expect(screen.getByRole("link", { name: "Browse competitions" })).toBeInTheDocument();
  });
});
