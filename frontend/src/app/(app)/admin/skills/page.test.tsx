import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import AdminSkillsPage from "@/app/(app)/admin/skills/page";
import type { AdminUserSkills, SkillMatrix } from "@/lib/types";

const mockMatrix = vi.fn();
const mockDetail = vi.fn();
const mockExport = vi.fn();

vi.mock("@/lib/hooks/use-permissions", () => ({
  useAccess: () => ({ ready: true, has: () => true }),
}));
vi.mock("@/lib/hooks/use-skills", () => ({
  useSkillMatrix: (...args: unknown[]) => mockMatrix(...args),
  useAdminUserSkills: (...args: unknown[]) => mockDetail(...args),
  useExportSkillMatrix: () => ({ mutate: mockExport, isPending: false }),
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

function cell(weighted: number, solved: number, overrides = {}) {
  return {
    weighted,
    solved,
    available: solved + 1,
    pct: 80,
    attempts: solved * 2,
    hints: 1,
    first_bloods: 0,
    ...overrides,
  };
}

const MATRIX: SkillMatrix = {
  skills: ["pwn", "web"],
  users: [
    {
      user_id: "u1",
      display_name: "ada",
      scores: { web: cell(200, 2, { first_bloods: 2 }), pwn: cell(100, 1) },
      total: 3,
      total_weighted: 300,
    },
  ],
  population: {
    web: { solvers: 1, mean_weighted: 200 },
    pwn: { solvers: 1, mean_weighted: 100 },
  },
  total_users: 1,
  limit: 25,
  offset: 0,
};

const DETAIL: AdminUserSkills = {
  user_id: "u1",
  display_name: "ada",
  skills: [
    { skill: "web", weighted: 200, solved: 2, attempts: 4, hints: 1, first_bloods: 2 },
  ],
  solves: [
    {
      challenge_title: "Heist",
      competition_name: "CTF",
      skill: "web",
      points_awarded: 150,
      attempts: 3,
      hints: 1,
      first_blood: true,
      solved_at: "2026-10-10T10:00:00Z",
    },
  ],
  total: 2,
  total_weighted: 200,
};

afterEach(() => {
  mockMatrix.mockReset();
  mockDetail.mockReset();
  mockExport.mockClear();
});

describe("AdminSkillsPage v2", () => {
  it("renders first-blood suffixes and passes the window to the query", () => {
    mockMatrix.mockReturnValue({ data: MATRIX, isLoading: false });
    mockDetail.mockReturnValue({ data: undefined, isLoading: false });
    renderWithIntl(<AdminSkillsPage />);

    expect(screen.getByText(/FB×2/)).toBeInTheDocument();
    // Default window reaches the hook…
    expect(mockMatrix.mock.calls[0][0]).toMatchObject({ window: "all", offset: 0 });
    // …and switching it refetches with the new window and a reset offset.
    fireEvent.change(screen.getByLabelText("Activity window"), {
      target: { value: "90" },
    });
    const last = mockMatrix.mock.calls.at(-1)![0];
    expect(last).toMatchObject({ window: "90", offset: 0 });
  });

  it("opens the drill-down on a row click", () => {
    mockMatrix.mockReturnValue({ data: MATRIX, isLoading: false });
    mockDetail.mockImplementation((userId: string | null) => ({
      data: userId ? DETAIL : undefined,
      isLoading: false,
    }));
    renderWithIntl(<AdminSkillsPage />);

    fireEvent.click(screen.getByText("ada"));
    // The dialog shows the user's solves with context + the first-blood mark.
    expect(screen.getByText("Heist")).toBeInTheDocument();
    expect(screen.getByText("CTF")).toBeInTheDocument();
    expect(screen.getByText("150")).toBeInTheDocument();
    expect(mockDetail.mock.calls.at(-1)![0]).toBe("u1");
  });

  it("exports with the active window", () => {
    mockMatrix.mockReturnValue({ data: MATRIX, isLoading: false });
    mockDetail.mockReturnValue({ data: undefined, isLoading: false });
    renderWithIntl(<AdminSkillsPage />);
    fireEvent.change(screen.getByLabelText("Activity window"), {
      target: { value: "30" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(mockExport.mock.calls[0][0]).toBe("30");
  });
});
