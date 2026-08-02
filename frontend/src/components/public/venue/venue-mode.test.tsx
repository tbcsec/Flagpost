import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { VenueMode } from "@/components/public/venue/venue-mode";
import type { PublicActivity, PublicScoreboard, PublicRecentSolve } from "@/lib/types";

const brand = { platform_name: "Flagpost", logo_url: null, show_wordmark: true };

const scoreboard: PublicScoreboard = {
  competition_id: "c1",
  mode: "individual",
  entries: [
    { rank: 1, subject_id: "t1", name: "SegfaultSquad", points: 4820, last_solve_at: null, bracket: null },
    { rank: 2, subject_id: "t2", name: "nullptr", points: 4610, last_solve_at: null, bracket: null },
  ],
  frozen: false,
  frozen_at: null,
  brackets: [],
  name: "Summer CTF",
  start_at: null,
  end_at: null,
};

function fb(challenge_id: string): PublicRecentSolve {
  return {
    challenge_id,
    title: challenge_id.toUpperCase(),
    subject_name: "nullptr",
    solved_at: "2026-08-02T12:00:00Z",
    points: 450,
    is_first_blood: true,
  };
}

function renderVenue(activity?: PublicActivity, onExit = vi.fn()) {
  return render(
    <VenueMode
      scoreboard={scoreboard}
      insights={undefined}
      activity={activity}
      brand={brand}
      intervalSeconds={15}
      onExit={onExit}
    />,
  );
}

describe("VenueMode", () => {
  it("shows the scoreboard slide with the leader and LIVE indicator", () => {
    renderVenue();
    expect(screen.getByText("Summer CTF")).toBeInTheDocument();
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    expect(screen.getByText("SegfaultSquad")).toBeInTheDocument();
    expect(screen.getByText("4,820")).toBeInTheDocument();
  });

  it("exits when the exit control is clicked", () => {
    const onExit = vi.fn();
    renderVenue(undefined, onExit);
    fireEvent.click(screen.getByRole("button", { name: "Exit venue" }));
    expect(onExit).toHaveBeenCalledTimes(1);
  });

  it("primes on the first feed so pre-existing first bloods don't splash", () => {
    renderVenue({ recent_solves: [fb("a")] });
    // 'a' is already-in-the-feed on load, so no takeover fires.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("splashes a first blood that appears after priming", () => {
    const { rerender } = renderVenue({ recent_solves: [fb("a")] });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    // A newer first blood arrives on the next poll → takeover.
    rerender(
      <VenueMode
        scoreboard={scoreboard}
        insights={undefined}
        activity={{ recent_solves: [fb("b"), fb("a")] }}
        brand={brand}
        intervalSeconds={15}
        onExit={vi.fn()}
      />,
    );
    const splash = screen.getByRole("alert");
    expect(splash).toHaveTextContent("First blood");
    expect(splash).toHaveTextContent("nullptr");
    expect(splash).toHaveTextContent("B");
  });
});
