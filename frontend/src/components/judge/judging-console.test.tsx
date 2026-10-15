import { fireEvent, screen, within } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { JudgingConsole } from "@/components/judge/judging-console";
import { toast } from "@/stores/toast";
import type { Judging, JudgingListFilters, JudgingQueue, StaffJudgingRow } from "@/lib/types";

// The jury console (#450). Hooks are scripted; the read-only code editor is
// stubbed (next/dynamic renders it synchronously as a <pre>).

vi.mock("next/dynamic", () => ({
  default: () =>
    function Code(props: { value: string }) {
      return <pre data-testid="code">{props.value}</pre>;
    } as ComponentType,
}));

const row = (over: Partial<StaffJudgingRow> = {}): StaffJudgingRow => ({
  id: "j1",
  code_submission_id: "cs1",
  challenge_id: "p1",
  challenge_title: "A + B",
  user_id: "u1",
  user_name: "alice",
  team_id: null,
  team_name: null,
  kind: "submit",
  origin: "submission",
  language_name: "Python 3",
  status: "done",
  verdict: "wrong_answer",
  submitted_at: "2026-10-15T10:00:00Z",
  created_at: "2026-10-15T10:00:00Z",
  finished_at: "2026-10-15T10:00:01Z",
  max_time_ms: 12,
  max_memory_kb: 9000,
  tests_passed: 1,
  tests_total: 3,
  requested_by_name: null,
  note: null,
  ...over,
});

const judging = (over: Partial<Judging> = {}): Judging => ({
  id: "j1",
  code_submission_id: "cs1",
  origin: "submission",
  challenge_id: "p1",
  user_id: "u1",
  team_id: null,
  kind: "submit",
  language_key: "python3",
  language_name: "Python 3",
  status: "done",
  verdict: "wrong_answer",
  queue_position: null,
  created_at: "2026-10-15T10:00:00Z",
  finished_at: "2026-10-15T10:00:01Z",
  compile_output: null,
  max_time_ms: 12,
  max_memory_kb: 9000,
  tests_passed: 1,
  tests_total: 3,
  tests: [
    { index: 0, sample: true, verdict: "accepted", time_ms: 5, memory_kb: 900, output: "5\n" },
    { index: 1, sample: false, verdict: "wrong_answer", time_ms: 12, memory_kb: 9000, output: null },
  ],
  ...over,
});

let rows: StaffJudgingRow[];
let queue: JudgingQueue;
let history: Judging[];
const listCalls: JudgingListFilters[] = [];
const rejudge = vi.fn();
const rejudgeProblem = vi.fn();
const override = vi.fn();

vi.mock("@/lib/hooks/use-challenges", () => ({
  useChallenges: () => ({
    data: [
      { id: "p1", title: "A + B", flag_type: "programming" },
      { id: "f1", title: "A flag", flag_type: "static" },
    ],
  }),
}));
vi.mock("@/lib/hooks/use-judge", () => ({
  useJudgingQueue: () => ({ data: queue }),
  useJudgingList: (_cid: string, filters: JudgingListFilters) => {
    listCalls.push(filters);
    return { data: { items: rows, total: rows.length }, isLoading: false };
  },
  useSubmissionHistory: () => ({ data: history, isLoading: false }),
  useJudgingSource: () => ({ data: { language_key: "python3", source: "print(4)" } }),
  useRejudge: () => ({ mutate: rejudge, isPending: false }),
  useRejudgeProblem: () => ({ mutate: rejudgeProblem, isPending: false, isError: false }),
  useOverrideVerdict: () => ({ mutate: override, isPending: false, isError: false }),
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

beforeEach(() => {
  rows = [row()];
  queue = { queued: 2, running: 1, site_queued: 5, site_running: 1, judge_enabled: true, problems: 1 };
  history = [judging()];
});
afterEach(() => {
  listCalls.length = 0;
  rejudge.mockClear();
  rejudgeProblem.mockClear();
  override.mockClear();
});

const page = (canAct = true) => renderWithIntl(<JudgingConsole competitionId="c1" canAct={canAct} />);

describe("JudgingConsole", () => {
  it("shows the queue and every submission", () => {
    page();
    expect(screen.getByText("2 waiting · 1 being judged")).toBeInTheDocument();
    expect(screen.getByText("5 waiting across the whole site")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("alice")).toBeInTheDocument();
    expect(within(table).getByText("Wrong answer")).toBeInTheDocument();
    expect(within(table).getByText("1/3")).toBeInTheDocument();
  });

  it("warns when the judge is switched off", () => {
    queue = { ...queue, judge_enabled: false };
    page();
    expect(screen.getByRole("alert")).toHaveTextContent("switched off");
  });

  it("filters by problem and result, and hides example runs by default", () => {
    page();
    expect(listCalls.at(-1)).toEqual({ challenge_id: undefined, verdict: undefined, kind: "submit" });
    fireEvent.change(screen.getByLabelText("Problem"), { target: { value: "p1" } });
    fireEvent.change(screen.getByLabelText("Result"), { target: { value: "accepted" } });
    fireEvent.click(screen.getByLabelText("Include example runs"));
    expect(listCalls.at(-1)).toEqual({ challenge_id: "p1", verdict: "accepted", kind: undefined });
    // Only programming problems are offered.
    expect(screen.queryByRole("option", { name: "A flag" })).toBeNull();
  });

  it("rejudges a whole problem with a chosen scope", () => {
    page();
    expect(screen.queryByRole("button", { name: "Rejudge this problem…" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Problem"), { target: { value: "p1" } });
    fireEvent.click(screen.getByRole("button", { name: "Rejudge this problem…" }));
    fireEvent.click(screen.getByLabelText(/Only submissions that weren't accepted/));
    fireEvent.click(screen.getByRole("button", { name: "Rejudge" }));
    expect(rejudgeProblem.mock.calls[0][0]).toEqual({ challengeId: "p1", only: "not_accepted" });
  });

  it("says how many overrides a bulk rejudge left alone", () => {
    page();
    fireEvent.change(screen.getByLabelText("Problem"), { target: { value: "p1" } });
    fireEvent.click(screen.getByRole("button", { name: "Rejudge this problem…" }));
    fireEvent.click(screen.getByRole("button", { name: "Rejudge" }));
    rejudgeProblem.mock.calls[0][1].onSuccess({ queued: 3, skipped: 0, overridden: 2 });
    expect(toast).toHaveBeenCalledWith("3 submissions queued for rejudging", {
      variant: "success",
      description:
        "2 decided by a judge's override were left alone — rejudge them one at a time to replace the overrides.",
    });
  });

  it("opens a submission with every test, its code and the actions", () => {
    page();
    fireEvent.click(within(screen.getByRole("table")).getByText("alice"));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Hidden test 2")).toBeInTheDocument();
    expect(within(dialog).getByTestId("code")).toHaveTextContent("print(4)");
    fireEvent.click(within(dialog).getByRole("button", { name: "Rejudge" }));
    expect(rejudge.mock.calls[0][0]).toBe("j1");
  });

  it("overrides only with a reason", () => {
    page();
    fireEvent.click(within(screen.getByRole("table")).getByText("alice"));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Override verdict…" }));
    const save = within(dialog).getByRole("button", { name: "Save verdict" });
    expect(save).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Reason (shown to staff)"), {
      target: { value: "Trailing zeros are fine" },
    });
    fireEvent.click(save);
    expect(override.mock.calls[0][0]).toEqual({
      judgingId: "j1",
      verdict: "accepted",
      reason: "Trailing zeros are fine",
    });
  });

  it("shows an override's author and reason, and the history", () => {
    history = [
      judging(),
      judging({
        id: "j2",
        origin: "override",
        verdict: "accepted",
        tests: [],
        requested_by_name: "Judge Judy",
        note: "Alternative output is valid",
      }),
    ];
    page();
    fireEvent.click(within(screen.getByRole("table")).getByText("alice"));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Verdict set by Judge Judy: “Alternative output is valid”")).toBeInTheDocument();
    expect(within(dialog).getByText("History")).toBeInTheDocument();
  });

  it("can't rejudge while one is already waiting", () => {
    history = [judging(), judging({ id: "j2", origin: "rejudge", status: "queued", verdict: null })];
    page();
    fireEvent.click(within(screen.getByRole("table")).getByText("alice"));
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Rejudge" })).toBeDisabled();
  });

  it("offers no actions without the rejudge permission", () => {
    page(false);
    fireEvent.change(screen.getByLabelText("Problem"), { target: { value: "p1" } });
    expect(screen.queryByRole("button", { name: "Rejudge this problem…" })).toBeNull();
    fireEvent.click(within(screen.getByRole("table")).getByText("alice"));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("button", { name: "Rejudge" })).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Override verdict…" })).toBeNull();
  });
});
