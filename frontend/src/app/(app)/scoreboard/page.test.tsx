import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import ScoreboardPage from "@/app/(app)/scoreboard/page";
import type { Scoreboard } from "@/lib/types";

// The staff live view during a freeze (#501): a scoreboard_freeze holder can
// switch the page to live standings; it starts on the frozen board, and an
// unfreeze switches it back.

let perms = new Set<string>();
let activeId = "c1";
const useScoreboard = vi.fn();
const useScoreboardTimeline = vi.fn((..._args: unknown[]) => ({ data: undefined }));

vi.mock("@/lib/hooks/use-competitions", () => ({
  useActiveCompetition: () => ({
    competitionId: activeId,
    data: { id: activeId, name: "Spring CTF", participation_mode: "team", status: "running" },
  }),
}));
vi.mock("@/lib/hooks/use-permissions", () => ({
  useAccess: () => ({ ready: true, has: (p: string) => perms.has(p) }),
}));
vi.mock("@/lib/hooks/use-scoreboard", () => ({
  useScoreboard: (...args: unknown[]) => useScoreboard(...args),
  useScoreboardTimeline: (...args: unknown[]) => useScoreboardTimeline(...args),
  useFreezeScoreboard: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/hooks/use-teams", () => ({ useMyTeam: () => ({ data: undefined }) }));
vi.mock("@/lib/hooks/use-brackets", () => ({
  useSetSubjectBracket: () => ({ mutate: vi.fn() }),
}));
vi.mock("@/components/certificates/scoreboard-certificate-card", () => ({
  ScoreboardCertificateCard: () => null,
}));
vi.mock("@/components/scoreboard/top-chart", () => ({ TopChart: () => null }));
vi.mock("@/components/public/points-timeline", () => ({ PointsTimeline: () => null }));
vi.mock("@/components/ui/confirm", () => ({ useConfirm: () => async () => true }));
vi.mock("@/stores/auth", () => ({
  useAuthStore: (select: (s: { user: { id: string } }) => unknown) =>
    select({ user: { id: "u1" } }),
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

function board(points: number, overrides: Partial<Scoreboard> = {}): Scoreboard {
  return {
    competition_id: "c1",
    mode: "team",
    entries: [
      { rank: 1, subject_id: "t1", name: "Rootkits", points, last_solve_at: null, bracket: null },
    ],
    frozen: false,
    frozen_at: null,
    live: false,
    brackets: [],
    ...overrides,
  };
}

const FROZEN = board(100, { frozen: true, frozen_at: "2026-10-18T10:00:00Z" });
const LIVE = board(400, { live: true });

/** Serve the frozen board to the shared view and the live one to the staff view. */
function serveFreeze() {
  useScoreboard.mockImplementation((_cid: string, opts?: { live?: boolean }) => ({
    data: opts?.live ? LIVE : FROZEN,
    isLoading: false,
    isError: false,
    socketStatus: "open",
  }));
}

function lastLive(): boolean {
  const opts = useScoreboard.mock.calls.at(-1)?.[1] as { live?: boolean } | undefined;
  return Boolean(opts?.live);
}

beforeEach(() => {
  perms = new Set(["challenge_view"]);
  activeId = "c1";
  useScoreboard.mockReset();
  useScoreboardTimeline.mockClear();
});

describe("ScoreboardPage during a freeze", () => {
  it("competitors get the frozen board and no switch", () => {
    serveFreeze();
    renderWithIntl(<ScoreboardPage />);
    expect(screen.getByText("The scoreboard is frozen.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show live standings" })).toBeNull();
    expect(lastLive()).toBe(false);
  });

  it("staff start on the frozen board and can switch to live standings", () => {
    perms.add("scoreboard_freeze");
    serveFreeze();
    renderWithIntl(<ScoreboardPage />);
    expect(lastLive()).toBe(false);
    expect(screen.getByText("100")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show live standings" }));
    expect(lastLive()).toBe(true);
    expect(useScoreboardTimeline.mock.calls.at(-1)?.[2]).toBe(true);
    expect(screen.getByText("You're viewing the live standings.")).toBeInTheDocument();
    expect(screen.getByText("400")).toBeInTheDocument();
    // Still frozen for competitors: the badge stays and Unfreeze is offered.
    expect(screen.getByText("Frozen")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unfreeze board" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show the frozen board" }));
    expect(lastLive()).toBe(false);
    expect(screen.getByText("The scoreboard is frozen.")).toBeInTheDocument();
  });

  it("an unfreeze ends the live view", () => {
    perms.add("scoreboard_freeze");
    serveFreeze();
    const { rerender } = renderWithIntl(<ScoreboardPage />);
    fireEvent.click(screen.getByRole("button", { name: "Show live standings" }));
    expect(lastLive()).toBe(true);

    // The live room's unfreeze frame: neither frozen nor live any more.
    useScoreboard.mockImplementation(() => ({
      data: board(400),
      isLoading: false,
      isError: false,
      socketStatus: "open",
    }));
    rerender(<ScoreboardPage />);
    expect(lastLive()).toBe(false);
    expect(screen.queryByRole("button", { name: "Show live standings" })).toBeNull();
    expect(screen.queryByText("Frozen")).toBeNull();
    expect(screen.getByRole("button", { name: "Freeze board" })).toBeInTheDocument();
  });

  it("switching competitions starts on the frozen board again", () => {
    perms.add("scoreboard_freeze");
    serveFreeze();
    const { rerender } = renderWithIntl(<ScoreboardPage />);
    fireEvent.click(screen.getByRole("button", { name: "Show live standings" }));
    expect(lastLive()).toBe(true);
    activeId = "c2";
    rerender(<ScoreboardPage />);
    expect(useScoreboard.mock.calls.at(-1)?.[0]).toBe("c2");
    expect(lastLive()).toBe(false);
    expect(screen.getByText("The scoreboard is frozen.")).toBeInTheDocument();
  });

  it("switching views doesn't flash the rows that moved since the freeze", () => {
    perms.add("scoreboard_freeze");
    serveFreeze();
    const { container } = renderWithIntl(<ScoreboardPage />);
    fireEvent.click(screen.getByRole("button", { name: "Show live standings" }));
    expect(container.querySelector(".bg-success\\/15")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show the frozen board" }));
    expect(container.querySelector(".bg-success\\/15")).toBeNull();
  });

  it("holds the Freeze control while there's no board to read the state from", () => {
    perms.add("scoreboard_freeze");
    useScoreboard.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      socketStatus: "connecting",
    });
    renderWithIntl(<ScoreboardPage />);
    expect(screen.getByRole("button", { name: "Freeze board" })).toBeDisabled();
  });

  it("offers no switch while the board isn't frozen", () => {
    perms.add("scoreboard_freeze");
    useScoreboard.mockReturnValue({
      data: board(100),
      isLoading: false,
      isError: false,
      socketStatus: "open",
    });
    renderWithIntl(<ScoreboardPage />);
    expect(screen.queryByRole("button", { name: "Show live standings" })).toBeNull();
  });
});
