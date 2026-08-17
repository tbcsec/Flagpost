import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { SubmissionsBrowser } from "@/components/analytics/submissions-browser";

// A filterable, paginated table over raw submission attempts (ROADMAP #76).
// Mock every domain hook it reads from so these tests drive pure component
// behaviour (filter-state transitions, empty/paginated render) — matching the
// announcement-banner test's hook-mocking pattern.
const mockUseChallenges = vi.fn();
const mockUseParticipants = vi.fn();
const mockUseTeams = vi.fn();
const mockUseSubmissionBrowser = vi.fn();
const mockUseExportSubmissions = vi.fn();

vi.mock("@/lib/hooks/use-challenges", () => ({
  useChallenges: (...args: unknown[]) => mockUseChallenges(...args),
}));
vi.mock("@/lib/hooks/use-participants", () => ({
  useParticipants: (...args: unknown[]) => mockUseParticipants(...args),
}));
vi.mock("@/lib/hooks/use-teams", () => ({
  useTeams: (...args: unknown[]) => mockUseTeams(...args),
}));
vi.mock("@/lib/hooks/use-submissions", () => ({
  useSubmissionBrowser: (...args: unknown[]) => mockUseSubmissionBrowser(...args),
  useExportSubmissions: (...args: unknown[]) => mockUseExportSubmissions(...args),
}));

function submission(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: "s1",
    challenge_id: "c1",
    user_id: "u1",
    team_id: null,
    value: "flag{nope}",
    correctness: "incorrect",
    points_awarded: 0,
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function page(items: ReturnType<typeof submission>[], total = items.length) {
  return { items, total, limit: 25, offset: 0 };
}

describe("SubmissionsBrowser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseChallenges.mockReturnValue({ data: [{ id: "c1", title: "Warmup" }] });
    mockUseParticipants.mockReturnValue({
      data: [{ user_id: "u1", display_name: "ada" }],
    });
    mockUseTeams.mockReturnValue({ data: [] });
    mockUseExportSubmissions.mockReturnValue({ mutate: vi.fn(), isPending: false });
  });

  it("renders rows with resolved challenge/user names", () => {
    mockUseSubmissionBrowser.mockReturnValue({
      data: page([submission()]),
      isLoading: false,
      isError: false,
    });
    renderWithIntl(<SubmissionsBrowser competitionId="comp-1" mode="individual" />);
    expect(screen.getByRole("cell", { name: "Warmup" })).toBeInTheDocument();
    expect(screen.getByText("ada")).toBeInTheDocument();
    expect(screen.getByText("flag{nope}")).toBeInTheDocument();
    expect(screen.getByText("incorrect")).toBeInTheDocument();
  });

  it("shows an empty state when nothing matches", () => {
    mockUseSubmissionBrowser.mockReturnValue({
      data: page([]),
      isLoading: false,
      isError: false,
    });
    renderWithIntl(<SubmissionsBrowser competitionId="comp-1" mode="individual" />);
    expect(screen.getByText("No submissions match these filters.")).toBeInTheDocument();
  });

  it("hides the team column in individual mode and shows it in team mode", () => {
    mockUseSubmissionBrowser.mockReturnValue({
      data: page([submission({ team_id: "t1" })]),
      isLoading: false,
      isError: false,
    });
    mockUseTeams.mockReturnValue({ data: [{ id: "t1", name: "Blue Team" }] });

    const { rerender } = renderWithIntl(
      <SubmissionsBrowser competitionId="comp-1" mode="individual" />,
    );
    expect(screen.queryByText("Blue Team")).not.toBeInTheDocument();

    rerender(<SubmissionsBrowser competitionId="comp-1" mode="team" />);
    expect(screen.getByText("Blue Team")).toBeInTheDocument();
  });

  it("applies filters into the query passed to the browser hook", () => {
    mockUseSubmissionBrowser.mockReturnValue({
      data: page([submission()]),
      isLoading: false,
      isError: false,
    });
    renderWithIntl(<SubmissionsBrowser competitionId="comp-1" mode="individual" />);

    fireEvent.change(screen.getByPlaceholderText("Search submitted payload…"), {
      target: { value: "haystack" },
    });
    fireEvent.change(screen.getByLabelText("Correctness"), {
      target: { value: "correct" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));

    const lastCall =
      mockUseSubmissionBrowser.mock.calls[mockUseSubmissionBrowser.mock.calls.length - 1];
    expect(lastCall[1]).toMatchObject({
      q: "haystack",
      correctness: "correct",
      offset: 0,
    });
  });

  it("resets filters back to the default query", () => {
    mockUseSubmissionBrowser.mockReturnValue({
      data: page([submission()]),
      isLoading: false,
      isError: false,
    });
    renderWithIntl(<SubmissionsBrowser competitionId="comp-1" mode="individual" />);

    fireEvent.change(screen.getByPlaceholderText("Search submitted payload…"), {
      target: { value: "haystack" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));

    const lastCall =
      mockUseSubmissionBrowser.mock.calls[mockUseSubmissionBrowser.mock.calls.length - 1];
    expect(lastCall[1]).toMatchObject({ offset: 0, limit: 25 });
    expect(lastCall[1].q).toBeUndefined();
    expect(lastCall[1].correctness).toBeUndefined();
  });

  it("pages forward and back, disabling Previous on the first page", () => {
    mockUseSubmissionBrowser.mockReturnValue({
      data: page([submission()], 60),
      isLoading: false,
      isError: false,
    });
    renderWithIntl(<SubmissionsBrowser competitionId="comp-1" mode="individual" />);

    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    const lastCall =
      mockUseSubmissionBrowser.mock.calls[mockUseSubmissionBrowser.mock.calls.length - 1];
    expect(lastCall[1]).toMatchObject({ offset: 25 });
  });

  it("triggers the CSV export mutation with the currently applied filters", () => {
    const mutate = vi.fn();
    mockUseExportSubmissions.mockReturnValue({ mutate, isPending: false });
    mockUseSubmissionBrowser.mockReturnValue({
      data: page([submission()]),
      isLoading: false,
      isError: false,
    });
    renderWithIntl(<SubmissionsBrowser competitionId="comp-1" mode="individual" />);

    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 25, offset: 0 }),
    );
  });
});
