import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { ProgrammingSection } from "@/components/challenges/programming-section";
import type { JudgeProblem, JudgeTestcase } from "@/lib/types";

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
    allowed_languages: null,
    testcases,
    default_time_limit_ms: 2000,
    default_memory_limit_mb: 256,
    default_output_limit_kb: 8192,
    ...over,
  };
}

let current = problem([]);
const addMutate = vi.fn();
const updateProblemMutate = vi.fn();
const deleteMutate = vi.fn();

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
}));
vi.mock("@/components/ui/confirm", () => ({ useConfirm: () => () => Promise.resolve(true) }));

afterEach(() => {
  current = problem([]);
  addMutate.mockClear();
  updateProblemMutate.mockClear();
  deleteMutate.mockClear();
});

describe("ProgrammingSection", () => {
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
      allowed_languages: ["c"],
    });
  });
});
