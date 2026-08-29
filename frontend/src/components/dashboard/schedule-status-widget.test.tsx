import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { ScheduleStatusWidget } from "@/components/dashboard/widgets";
import type { Competition } from "@/lib/types";

// Schedule & status widget (#332): status (with paused override), the next
// schedule boundary countdown, and the scoreboard-freeze flag — all derived from
// the competition row (no dashboard endpoint).

let comp: Partial<Competition>;
vi.mock("@/lib/hooks/use-competitions", () => ({
  useCompetition: () => ({ data: comp, isLoading: false }),
}));
vi.mock("@/lib/hooks/use-relative-time", () => ({
  useRelativeTime: () => () => "in 2 hours",
}));

beforeEach(() => {
  comp = {
    status: "running",
    paused: false,
    start_at: null,
    end_at: "2030-01-01T00:00:00Z",
    scoreboard_frozen_at: null,
  };
});

describe("ScheduleStatusWidget", () => {
  it("shows the running status and the end countdown", () => {
    renderWithIntl(<ScheduleStatusWidget competitionId="c1" />);
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByText(/ends in 2 hours/i)).toBeInTheDocument();
  });

  it("shows Paused when paused overrides the coarse status", () => {
    comp.paused = true;
    renderWithIntl(<ScheduleStatusWidget competitionId="c1" />);
    expect(screen.getByText("Paused")).toBeInTheDocument();
  });

  it("flags a frozen scoreboard", () => {
    comp.scoreboard_frozen_at = "2025-01-01T00:00:00Z";
    renderWithIntl(<ScheduleStatusWidget competitionId="c1" />);
    expect(screen.getByText(/scoreboard is frozen/i)).toBeInTheDocument();
  });
});
