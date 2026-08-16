import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TopChart } from "@/components/scoreboard/top-chart";
import { renderWithIntl } from "@/test/intl";
import type { ScoreboardEntry } from "@/lib/types";

function entry(over: Partial<ScoreboardEntry>): ScoreboardEntry {
  return {
    rank: 1,
    subject_id: "s1",
    name: "Subject",
    points: 100,
    last_solve_at: null,
    bracket: null,
    ...over,
  };
}

const BOARD: ScoreboardEntry[] = [
  entry({
    rank: 1,
    subject_id: "a",
    name: "Alpha",
    points: 500,
    last_solve_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    bracket: "Students",
  }),
  entry({ rank: 2, subject_id: "b", name: "Bravo", points: 300 }),
  entry({ rank: 3, subject_id: "c", name: "Charlie", points: 0 }),
];

describe("TopChart", () => {
  it("gives every column a screen-reader label carrying the tooltip's facts", () => {
    renderWithIntl(<TopChart entries={BOARD} mySubjectId={null} isTeam={false} />);
    expect(
      screen.getByRole("button", {
        name: /Rank 1: Alpha, 500 points, last solve .*, division Students/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Rank 2: Bravo, 300 points, no solves yet" }),
    ).toBeInTheDocument();
  });

  it("marks the viewer's own subject, worded for the mode", () => {
    const { rerender } = renderWithIntl(
      <TopChart entries={BOARD} mySubjectId="b" isTeam={false} />,
    );
    expect(
      screen.getByRole("button", { name: /Rank 2: Bravo \(you\)/ }),
    ).toBeInTheDocument();

    rerender(<TopChart entries={BOARD} mySubjectId="b" isTeam={true} />);
    expect(
      screen.getByRole("button", { name: /Rank 2: Bravo \(your team\)/ }),
    ).toBeInTheDocument();
  });

  it("reveals the tooltip on focus and hides it on blur", () => {
    renderWithIntl(<TopChart entries={BOARD} mySubjectId={null} isTeam={false} />);
    const bar = screen.getByRole("button", { name: /Rank 1: Alpha/ });
    const tooltip = () => bar.querySelector('div[aria-hidden="true"]');

    expect(tooltip()).not.toHaveAttribute("data-open");
    fireEvent.focus(bar);
    expect(tooltip()).toHaveAttribute("data-open");
    fireEvent.blur(bar);
    expect(tooltip()).not.toHaveAttribute("data-open");
  });

  it("reveals on hover, one column at a time", () => {
    renderWithIntl(<TopChart entries={BOARD} mySubjectId={null} isTeam={false} />);
    const alpha = screen.getByRole("button", { name: /Rank 1: Alpha/ });
    const bravo = screen.getByRole("button", { name: /Rank 2: Bravo/ });
    const open = (b: HTMLElement) =>
      b.querySelector('div[aria-hidden="true"]')!.hasAttribute("data-open");

    fireEvent.mouseEnter(alpha);
    expect(open(alpha)).toBe(true);
    fireEvent.mouseEnter(bravo);
    expect(open(bravo)).toBe(true);
    expect(open(alpha)).toBe(false);
    fireEvent.mouseLeave(bravo);
    expect(open(bravo)).toBe(false);
  });

  it("carries the detail content (name, points, last solve, division)", () => {
    renderWithIntl(<TopChart entries={BOARD} mySubjectId={null} isTeam={false} />);
    expect(screen.getByText("Division: Students")).toBeInTheDocument();
    expect(screen.getByText(/Last solve/)).toBeInTheDocument();
    expect(screen.getAllByText("No solves yet")).toHaveLength(2);
  });

  it("shows at-a-glance labels without hover: points above, rank · name below", () => {
    renderWithIntl(<TopChart entries={BOARD} mySubjectId={null} isTeam={false} />);
    // Points figure appears in the plot label and the tooltip for each column.
    expect(screen.getAllByText("500").length).toBeGreaterThanOrEqual(2);
    // Under-bar label carries rank + name (aria-hidden, so query by text).
    expect(screen.getAllByText("Bravo").length).toBeGreaterThanOrEqual(2);
  });

  it("scales bars to points, zero staying a zero-height bar not a crash", () => {
    const { container } = renderWithIntl(
      <TopChart entries={BOARD} mySubjectId={null} isTeam={false} />,
    );
    const heights = [...container.querySelectorAll("div[style]")]
      .map((el) => (el as HTMLElement).style.height)
      .filter(Boolean);
    // Leader gets the full (headroom-scaled) height; zero points → 0%.
    expect(heights[0]).toBe("86%");
    expect(heights[2]).toBe("0%");
  });
});
