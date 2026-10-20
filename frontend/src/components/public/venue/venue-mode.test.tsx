import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { VenueMode } from "@/components/public/venue/venue-mode";
import { renderWithIntl } from "@/test/intl";
import type {
  PublicActivity,
  PublicInsights,
  PublicScoreboard,
  PublicRecentSolve,
} from "@/lib/types";

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
  live: false,
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

const T0 = Date.parse("2026-08-02T10:00:00Z");
const at = (minutes: number) => new Date(T0 + minutes * 60_000).toISOString();

const insights: PublicInsights = {
  frozen: false,
  frozen_at: null,
  stats: { participants: 42, solves: 17, challenges: 20, unsolved: 6 },
  highlights: {
    most_solved: { title: "Warmup", count: 9 },
    most_attempted: { title: "Crypto 3", count: 31 },
    first_blood_leader: { name: "SegfaultSquad", count: 4 },
    fastest_solve: { title: "Warmup", name: "nullptr", seconds: 95 },
  },
  categories: [
    { name: "Crypto", challenges: 4, solved: 0, solves: 0 },
    { name: "Web", challenges: 3, solved: 2, solves: 9 },
    { name: null, challenges: 1, solved: 1, solves: 1 },
  ],
  timeline: {
    start: at(0),
    end: at(60),
    series: [
      {
        subject_id: "t1",
        name: "SegfaultSquad",
        points: [
          { t: at(0), points: 0 },
          { t: at(10), points: 1000 },
          { t: at(50), points: 4820 },
        ],
      },
      {
        subject_id: "t2",
        name: "nullptr",
        points: [
          { t: at(0), points: 0 },
          { t: at(20), points: 2000 },
          { t: at(30), points: 4610 },
        ],
      },
    ],
  },
};

function renderVenue(activity?: PublicActivity, onExit = vi.fn(), withInsights?: PublicInsights) {
  return renderWithIntl(
    <VenueMode
      scoreboard={scoreboard}
      insights={withInsights}
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

  it("rotates to a stats slide with the live solve ticker and the records (#513)", () => {
    const feed: PublicActivity = {
      recent_solves: [
        { ...fb("c1"), subject_name: "nullptr", title: "Crypto 1", is_first_blood: true },
        { ...fb("c2"), subject_name: "nullptr", title: "Web 2", is_first_blood: false },
        { ...fb("c3"), subject_name: "SegfaultSquad", title: "Pwn 3", is_first_blood: false },
      ],
    };
    renderVenue(feed, vi.fn(), insights);
    fireEvent.keyDown(window, { key: "ArrowRight" });

    const ticker = screen.getByRole("region", { name: "Live solves" });
    const rows = within(ticker).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("nullptr solved Crypto 1");
    expect(rows[0]).toHaveTextContent("+450");

    // Counts, then the records: the existing highlights plus the race records
    // derived from the board, the timeline and the feed.
    expect(screen.getByText("42")).toBeInTheDocument();
    const records = screen.getByRole("region", { name: "Records" });
    expect(records).toHaveTextContent("Most first bloods");
    expect(records).toHaveTextContent("Fastest solve");
    expect(records).toHaveTextContent("Warmup · 1m");
    // Closest race: #1 4820 vs #2 4610.
    expect(records).toHaveTextContent("210 pts apart");
    expect(records).toHaveTextContent("#1 SegfaultSquad vs #2 nullptr");
    // Hot streak: nullptr's two newest solves in a row.
    expect(records).toHaveTextContent("2 solves in a row");
    // Biggest climb: SegfaultSquad passed nullptr at 50 min, inside the window.
    expect(records).toHaveTextContent("Biggest climb");
    expect(records).toHaveTextContent("up 1 place");

    // The category bars: solved out of visible, untouched called out.
    const categories = screen.getByRole("region", { name: "By category" });
    expect(categories).toHaveTextContent("Crypto");
    expect(categories).toHaveTextContent("4 untouched");
    expect(categories).toHaveTextContent("Web");
    expect(categories).toHaveTextContent("2/3 · 9 solves");
    expect(categories).toHaveTextContent("Uncategorised");
    expect(screen.getByRole("meter", { name: "Web" })).toHaveAttribute("aria-valuenow", "2");
  });

  it("says so on the stats slide when no one has solved anything yet", () => {
    renderVenue({ recent_solves: [] }, vi.fn(), insights);
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByText(/No solves yet/)).toBeInTheDocument();
  });

  it("rotates on to the timeline slide with the race panel (#513)", () => {
    renderVenue(undefined, vi.fn(), insights);
    fireEvent.keyDown(window, { key: "ArrowRight" });
    fireEvent.keyDown(window, { key: "ArrowRight" });

    const race = screen.getByRole("complementary", { name: "The race" });
    expect(race).toHaveTextContent("Lead margin");
    expect(race).toHaveTextContent("+210");
    expect(race).toHaveTextContent("SegfaultSquad over nullptr");
    // nullptr went ahead at 20 min, SegfaultSquad took it back at 50.
    expect(race).toHaveTextContent("Lead changes");
    expect(race).toHaveTextContent(/Last: SegfaultSquad at/);
    // Biggest climber over the last 30 min of the series: SegfaultSquad +3820.
    expect(race).toHaveTextContent("+3,820");
    // The old card chrome is gone: no "Top N entrants" subtitle, no legend.
    expect(screen.queryByText(/Top 2 entrants/)).not.toBeInTheDocument();
  });

  it("skips the timeline slide while nobody has scored", () => {
    const empty: PublicInsights = {
      ...insights,
      timeline: {
        ...insights.timeline,
        series: insights.timeline.series.map((s) => ({
          ...s,
          points: s.points.map((p) => ({ ...p, points: 0 })),
        })),
      },
    };
    renderVenue(undefined, vi.fn(), empty);
    expect(screen.getAllByRole("tab")).toHaveLength(2);
  });

  it("draws the chart with a label per line once its box has a size", () => {
    // jsdom lays nothing out, so give every box a size: the chart fills it.
    const rect = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: 800,
      height: 400,
      top: 0,
      left: 0,
      right: 800,
      bottom: 400,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    try {
      renderVenue(undefined, vi.fn(), insights);
      fireEvent.keyDown(window, { key: "ArrowRight" });
      fireEvent.keyDown(window, { key: "ArrowRight" });
      const chart = screen.getByRole("img", { name: /top 2 entrants.*SegfaultSquad leads/ });
      expect(chart).toBeInTheDocument();
      const labels = screen.getAllByTestId("end-label");
      expect(labels).toHaveLength(2);
      expect(labels[0]).toHaveTextContent("SegfaultSquad");
      expect(labels[0]).toHaveTextContent("4,820");
      expect(labels[1]).toHaveTextContent("nullptr");
    } finally {
      rect.mockRestore();
    }
  });

  it("fills the board with the rows that fit, never a scrollbar (#513)", () => {
    const thirty: PublicScoreboard = {
      ...scoreboard,
      entries: Array.from({ length: 30 }, (_, i) => ({
        rank: i + 1,
        subject_id: `s${i + 1}`,
        name: `Team ${i + 1}`,
        points: 1000 - i * 10,
        last_solve_at: null,
        bracket: null,
      })),
    };
    // A 700px list whose rows are 40px tall holds seventeen rows — there's no
    // fixed cap, the screen decides.
    const height = vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(700);
    const rect = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: 0,
      height: 40,
      top: 0,
      left: 0,
      right: 0,
      bottom: 40,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    try {
      renderWithIntl(
        <VenueMode
          scoreboard={thirty}
          insights={undefined}
          activity={undefined}
          brand={brand}
          intervalSeconds={15}
          onExit={vi.fn()}
        />,
      );
      expect(screen.getByText("Team 1")).toBeInTheDocument();
      expect(screen.getByText("Team 17")).toBeInTheDocument();
      expect(screen.queryByText("Team 18")).not.toBeInTheDocument();
    } finally {
      height.mockRestore();
      rect.mockRestore();
    }
  });
});
