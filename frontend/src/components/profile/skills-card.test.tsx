import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MySkillsCard } from "@/components/profile/skills-card";
import type { UserSkills } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";

let state: { data?: UserSkills; isLoading: boolean; isError: boolean } = {
  data: undefined,
  isLoading: false,
  isError: false,
};

vi.mock("@/lib/hooks/use-skills", () => ({
  useMySkills: () => state,
}));

describe("MySkillsCard", () => {
  it("shows the empty state when the web has no skills", () => {
    state = {
      data: { skills: [], total: 0, competitions_played: 0 },
      isLoading: false,
      isError: false,
    };
    renderWithIntl(<MySkillsCard />);
    expect(screen.getByText(/No skills yet/i)).toBeInTheDocument();
  });

  it("renders the summary, breakdown, and radar for a populated web", () => {
    state = {
      data: {
        skills: [
          { skill: "web", score: 4 },
          { skill: "pwn", score: 2 },
          { skill: "crypto", score: 1 },
        ],
        total: 7,
        competitions_played: 2,
      },
      isLoading: false,
      isError: false,
    };
    renderWithIntl(<MySkillsCard />);
    // Cross-competition summary.
    expect(screen.getByText(/7 solves across 2 competitions/i)).toBeInTheDocument();
    // The radar (≥3 axes) renders as a labelled SVG.
    expect(
      screen.getByRole("img", { name: /Skills web across 3 categories/i }),
    ).toBeInTheDocument();
    // Each skill appears at least once (radar label + breakdown row).
    expect(screen.getAllByText("web").length).toBeGreaterThan(0);
    expect(screen.getAllByText("crypto").length).toBeGreaterThan(0);
  });

  it("skips the radar but keeps the breakdown below three skills", () => {
    state = {
      data: { skills: [{ skill: "web", score: 3 }], total: 3, competitions_played: 1 },
      isLoading: false,
      isError: false,
    };
    renderWithIntl(<MySkillsCard />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("web")).toBeInTheDocument();
  });
});
