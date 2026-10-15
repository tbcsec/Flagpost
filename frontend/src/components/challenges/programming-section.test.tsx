import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { ProgrammingSection } from "@/components/challenges/programming-section";
import type { ComponentType } from "react";

import type { JudgeProblem, JudgeTestcase, Judging, ReferenceCheck } from "@/lib/types";

// The test-case editor for a programming challenge (#447): the common path is
// "Add test case" with pasted text; limits/comparison/languages hide behind a
// closed Advanced where blank means "use the default".

function tc(partial: Partial<JudgeTestcase> & { id: string }): JudgeTestcase {
  return {
    sample: false,
    input_bytes: 4,
    answer_bytes: 2,
    input_preview: "1 2\n",
    answer_preview: "3\n",
    ...partial,
  };
}

function problem(testcases: JudgeTestcase[], over: Partial<JudgeProblem> = {}): JudgeProblem {
  return {
    time_limit_ms: null,
    memory_limit_mb: null,
    output_limit_kb: null,
    compare_mode: "token",
    float_tolerance: null,
    case_insensitive: false,
    allowed_languages: null,
    testcases,
    default_time_limit_ms: 2000,
    default_memory_limit_mb: 256,
    default_output_limit_kb: 8192,
    ...over,
  };
}

let current = problem([]);
let reference: ReferenceCheck = {
  judging: null, run_by_name: null, language_key: null, source: null, stale: false,
};
const runReference = vi.fn();
const addMutate = vi.fn();
const updateProblemMutate = vi.fn();
const deleteMutate = vi.fn();
const exportMutate = vi.fn();
const toastSpy = vi.fn();

vi.mock("@/lib/hooks/use-judge", () => ({
  useJudgeProblem: () => ({ data: current, isError: false }),
  useJudgeStatus: () => ({
    data: {
      module_enabled: true,
      judge_enabled: true,
      ready: true,
      languages: [
        { key: "python3", name: "Python 3" },
        { key: "c", name: "C" },
      ],
    },
  }),
  useJudgeTestcase: () => ({ data: undefined, isLoading: true, isError: false }),
  useAddJudgeTestcase: () => ({ mutate: addMutate, isPending: false, reset: vi.fn() }),
  useUploadJudgeTestcase: () => ({ mutate: vi.fn(), isPending: false, reset: vi.fn() }),
  useUpdateJudgeTestcase: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteJudgeTestcase: () => ({ mutate: deleteMutate, isPending: false }),
  useUpdateJudgeProblem: () => ({ mutate: updateProblemMutate, isPending: false }),
  useReferenceCheck: () => ({ data: reference }),
  useExportProblemPackage: () => ({ mutate: exportMutate, isPending: false }),
  useRunReferenceCheck: () => ({ mutate: runReference, isPending: false, isError: false, reset: vi.fn() }),
}));
// The code editor (CodeMirror, loaded with next/dynamic) as a plain textarea.
vi.mock("next/dynamic", () => ({
  default: () =>
    function Code(props: { value: string; onChange?: (v: string) => void; ariaLabel: string }) {
      return (
        <textarea
          aria-label={props.ariaLabel}
          value={props.value}
          onChange={(e) => props.onChange?.(e.target.value)}
        />
      );
    } as ComponentType,
}));
vi.mock("@/components/ui/confirm", () => ({ useConfirm: () => () => Promise.resolve(true) }));
vi.mock("@/stores/toast", () => ({ toast: (...args: unknown[]) => toastSpy(...args) }));

afterEach(() => {
  current = problem([]);
  reference = { judging: null, run_by_name: null, language_key: null, source: null, stale: false };
  runReference.mockClear();
  addMutate.mockClear();
  updateProblemMutate.mockClear();
  deleteMutate.mockClear();
  exportMutate.mockReset();
  toastSpy.mockClear();
});

describe("ProgrammingSection", () => {
  it("exports the package, and says why when it can't", () => {
    current = problem([tc({ id: "a" })]);
    exportMutate.mockImplementation((_: unknown, opts: { onError: (e: Error) => void }) =>
      opts.onError(new Error("The test data for “Sum” couldn't be read from storage")),
    );
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    fireEvent.click(screen.getByRole("button", { name: "Export package" }));
    expect(exportMutate).toHaveBeenCalledTimes(1);
    expect(toastSpy).toHaveBeenCalledWith("Export failed", {
      description: "The test data for “Sum” couldn't be read from storage",
      variant: "destructive",
    });
  });

  it("prompts for a first test case", () => {
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    expect(screen.getByText(/No test cases yet/)).toBeInTheDocument();
  });

  it("warns when every test case is an example", () => {
    current = problem([tc({ id: "a", sample: true })]);
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    expect(screen.getByText(/Every test case is shown to competitors/)).toBeInTheDocument();
  });

  it("lists cases with example/hidden badges and no warning when one is hidden", () => {
    current = problem([tc({ id: "a", sample: true }), tc({ id: "b" })]);
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    expect(screen.getByText("Example")).toBeInTheDocument();
    expect(screen.getByText("Hidden")).toBeInTheDocument();
    expect(screen.queryByText(/Every test case is shown/)).toBeNull();
  });

  it("adds a pasted test case", () => {
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    fireEvent.click(screen.getByRole("button", { name: "Add test case" }));
    fireEvent.change(screen.getByLabelText("Input"), { target: { value: "2 3" } });
    fireEvent.change(screen.getByLabelText("Expected output"), { target: { value: "5" } });
    fireEvent.click(screen.getByLabelText(/Show to competitors as an example/));
    const dialog = screen.getByRole("dialog");
    fireEvent.submit(dialog.querySelector("form")!);
    expect(addMutate.mock.calls[0][0]).toEqual({ input: "2 3", answer: "5", sample: true });
  });

  it("removes a test case after confirming", async () => {
    current = problem([tc({ id: "a" })]);
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(deleteMutate).toHaveBeenCalledWith("a"));
  });

  it("saves 'every language' as the default, not an empty list", () => {
    current = problem([tc({ id: "a" })]);
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    fireEvent.click(screen.getByRole("button", { name: "Save options" }));
    expect(updateProblemMutate.mock.calls[0][0].allowed_languages).toBeNull();
  });

  it("saves advanced options with blanks meaning the default", () => {
    current = problem([tc({ id: "a" })], { time_limit_ms: 5000 });
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    // Blank fields show the default they fall back to.
    expect(screen.getByLabelText("Memory limit (MB)")).toHaveAttribute(
      "placeholder",
      "Default: 256",
    );
    fireEvent.change(screen.getByLabelText("Time limit (ms)"), { target: { value: "" } });
    fireEvent.click(screen.getByLabelText(/Allow every language/));
    fireEvent.click(screen.getByLabelText("C"));
    fireEvent.click(screen.getByRole("button", { name: "Save options" }));
    expect(updateProblemMutate.mock.calls[0][0]).toEqual({
      time_limit_ms: null,
      memory_limit_mb: null,
      output_limit_kb: null,
      compare_mode: "token",
      float_tolerance: null,
      case_insensitive: false,
      allowed_languages: ["c"],
    });
  });

  it("can ignore upper/lower case", () => {
    current = problem([tc({ id: "a" })]);
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    fireEvent.click(screen.getByLabelText(/Ignore upper\/lower case/));
    fireEvent.click(screen.getByRole("button", { name: "Save options" }));
    expect(updateProblemMutate.mock.calls[0][0].case_insensitive).toBe(true);
  });
});


const judging = (over: Partial<Judging> = {}): Judging => ({
  id: "j1",
  code_submission_id: "cs1",
  origin: "submission",
  challenge_id: "p",
  user_id: "u1",
  team_id: null,
  kind: "reference",
  language_key: "python3",
  language_name: "Python 3",
  status: "done",
  verdict: "wrong_answer",
  queue_position: null,
  created_at: "2026-10-15T10:00:00Z",
  finished_at: "2026-10-15T10:00:01Z",
  compile_output: null,
  max_time_ms: 30,
  max_memory_kb: 9000,
  tests_passed: 2,
  tests_total: 3,
  tests: [
    { index: 0, sample: true, verdict: "accepted", time_ms: 10, memory_kb: 900, output: null },
    { index: 1, sample: false, verdict: "wrong_answer", time_ms: 30, memory_kb: 9000, output: null },
    { index: 2, sample: false, verdict: "accepted", time_ms: 20, memory_kb: 900, output: null },
  ],
  ...over,
});

describe("the reference-solution check", () => {
  const three = [tc({ id: "a", sample: true }), tc({ id: "b" }), tc({ id: "c" })];

  it("isn't offered until there are test cases", () => {
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    expect(screen.queryByText("Check with a reference solution")).toBeNull();
  });

  it("runs a pasted solution against every test", () => {
    current = problem(three);
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    expect(screen.getByText(/it never stops you publishing/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Test with a reference solution…" }));
    fireEvent.change(screen.getByLabelText("Reference solution"), {
      target: { value: "print(sum(map(int, input().split())))" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run check" }));
    expect(runReference.mock.calls[0][0]).toEqual({
      language: "python3",
      source: "print(sum(map(int, input().split())))",
    });
  });

  it("shows each test's result, numbered as in the list, and runs it again", () => {
    current = problem(three);
    reference = {
      judging: judging(), run_by_name: "Ada", language_key: "python3", source: "print(1)", stale: false,
    };
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    expect(screen.getByText("1 of 3 tests failed")).toBeInTheDocument();
    const results = screen.getAllByText(/^(Accepted|Wrong answer)$/).map((n) => n.textContent);
    expect(results).toEqual(["Accepted", "Wrong answer", "Accepted"]);
    fireEvent.click(screen.getByRole("button", { name: "Run again" }));
    expect(runReference.mock.calls[0][0]).toEqual({ language: "python3", source: "print(1)" });
  });

  it("says when the check is out of date, and what didn't run", () => {
    current = problem(three);
    reference = {
      judging: judging({ tests: judging().tests.slice(0, 2) }),
      run_by_name: "Ada", language_key: "python3", source: "print(1)", stale: true,
    };
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    expect(screen.getByRole("status")).toHaveTextContent("changed after this check");
    expect(screen.getByText("Not run")).toBeInTheDocument();
  });

  it("celebrates a clean pass", () => {
    current = problem(three);
    reference = {
      judging: judging({ verdict: "accepted", tests_passed: 3 }),
      run_by_name: "Ada", language_key: "python3", source: "print(1)", stale: false,
    };
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    expect(screen.getByText("Passed all 3 tests")).toBeInTheDocument();
  });

  it("won't rerun in a language the problem no longer allows", () => {
    current = problem(three, { allowed_languages: ["c"] });
    reference = {
      judging: judging(), run_by_name: "Ada", language_key: "python3", source: "print(1)", stale: true,
    };
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    expect(screen.getByRole("button", { name: "Run again" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Change solution…" }));
    expect(screen.getByLabelText("Language")).toHaveValue("c");
  });

  it("offers the package's own solution before any check has run", () => {
    current = problem(three);
    reference = { judging: null, run_by_name: null, language_key: "python3", source: "print(1)", stale: false };
    renderWithIntl(<ProgrammingSection competitionId="c" challengeId="p" />);
    expect(screen.getByText(/The package's accepted Python 3 solution is ready/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Test with a reference solution…" }));
    expect(screen.getByLabelText("Reference solution")).toHaveValue("print(1)");
  });
});
