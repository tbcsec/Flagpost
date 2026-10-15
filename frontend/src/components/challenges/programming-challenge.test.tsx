import { fireEvent, screen } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import {
  languageForFile,
  ProgrammingChallenge,
} from "@/components/challenges/programming-challenge";
import type { Challenge, Judging, ProblemView } from "@/lib/types";

// The problem page (#449). CodeMirror is replaced by a textarea (next/dynamic
// is stubbed to render it synchronously); the hooks are scripted.

vi.mock("next/dynamic", () => ({
  default: () =>
    function Editor(props: { value: string; onChange: (v: string) => void; ariaLabel: string }) {
      return (
        <textarea
          aria-label={props.ariaLabel}
          value={props.value}
          onChange={(e) => props.onChange(e.target.value)}
        />
      );
    } as ComponentType,
}));
vi.mock("@/components/ui/rich-text-view", () => ({
  RichTextView: () => <div>Read two integers and print their sum.</div>,
}));
vi.mock("@/components/ui/confirm", () => ({ useConfirm: () => () => Promise.resolve(true) }));
// Questions and clarifications have their own test (problem-clarifications).
vi.mock("@/components/challenges/challenge-files", () => ({ ChallengeFiles: () => null }));
vi.mock("@/components/challenges/problem-clarifications", () => ({
  ProblemClarifications: () => <div data-testid="clarifications" />,
  ClarificationsLink: () => null,
}));

const challenge: Challenge = {
  id: "ch1",
  competition_id: "c1",
  title: "A + B",
  description: { type: "doc", content: [] },
  category_id: null,
  points: 150,
  scoring_type: "static",
  min_points: null,
  decay: null,
  value: 150,
  release_at: null,
  prerequisites: [],
  locked: false,
  tags: [],
  difficulty: null,
  connection_info: null,
  state: "published",
  flag_type: "programming",
  case_insensitive: false,
  has_flag: false,
  choices: null,
  attempts_remaining: null,
  subject_value: null,
  my_rating: null,
  solved: false,
  solve_count: 2,
  instanced: false,
  created_at: "2026-01-01T00:00:00Z",
};

let problem: ProblemView;
let judgings: Judging[];
let theChallenge: Challenge;
const submitMutate = vi.fn();

function judging(over: Partial<Judging>): Judging {
  return {
    id: "j1",
    code_submission_id: "cs1",
    origin: "submission",
    challenge_id: "ch1",
    user_id: "u1",
    team_id: null,
    kind: "submit",
    language_key: "python3",
    language_name: "Python 3",
    status: "done",
    verdict: "accepted",
    queue_position: null,
    created_at: "2026-01-01T00:00:00Z",
    finished_at: "2026-01-01T00:00:01Z",
    compile_output: null,
    max_time_ms: 12,
    max_memory_kb: 9000,
    tests_passed: 3,
    tests_total: 3,
    tests: [],
    ...over,
  };
}

vi.mock("@/lib/hooks/use-challenges", () => ({
  useChallenge: () => ({ data: theChallenge, isLoading: false, error: null }),
  useChallenges: () => ({ data: [theChallenge] }),
}));
vi.mock("@/lib/hooks/use-categories", () => ({ useCategories: () => ({ data: [] }) }));
vi.mock("@/lib/hooks/use-judge", () => ({
  useProblemView: () => ({ data: problem, isLoading: false, error: null }),
  useMyJudgings: () => ({ data: judgings }),
  useSubmitCode: () => ({ mutate: submitMutate, isPending: false, isError: false, error: null }),
  useLoadJudgingSource: () => ({ mutate: vi.fn(), isPending: false }),
}));

beforeEach(() => {
  theChallenge = challenge;
  judgings = [];
  problem = {
    time_limit_ms: 2000,
    memory_limit_mb: 256,
    output_limit_kb: 8192,
    compare_mode: "token",
    float_tolerance: null,
    languages: [
      { key: "python3", name: "Python 3", time_limit_ms: 3000, extension: ".py" },
      { key: "pypy3", name: "PyPy 3", time_limit_ms: 2000, extension: ".py" },
      { key: "cpp", name: "C++", time_limit_ms: 2000, extension: ".cpp" },
    ],
    examples: [{ index: 0, input: "2 3\n", answer: "5\n", truncated: false }],
    judge_ready: true,
  };
  window.localStorage.clear();
});

afterEach(() => submitMutate.mockClear());

const page = () => renderWithIntl(<ProgrammingChallenge competitionId="c1" challengeId="ch1" />);
const editor = () => screen.getByLabelText("Your solution") as HTMLTextAreaElement;
const writeTab = () => fireEvent.click(screen.getByRole("tab", { name: "Write code" }));

describe("ProgrammingChallenge", () => {
  it("shows the statement, a quiet limits line and the examples", () => {
    page();
    expect(screen.getByRole("heading", { name: "A + B" })).toBeInTheDocument();
    expect(screen.getByText("Read two integers and print their sum.")).toBeInTheDocument();
    // The time limit is the chosen language's (Python's multiplier applied).
    expect(screen.getByText(/Time limit 3 s · Memory limit 256 MB/)).toBeInTheDocument();
    // How output is compared isn't the competitor's concern (owner decision).
    expect(screen.queryByText("Whitespace ignored")).toBeNull();
    expect(screen.getByText("Example 1 — input")).toBeInTheDocument();
    // Questions and the judges' clarifications sit under the statement.
    expect(screen.getByTestId("clarifications")).toBeInTheDocument();
  });

  it("submits and runs code written in the browser", () => {
    page();
    writeTab();
    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit).toBeDisabled(); // nothing written yet
    fireEvent.change(editor(), { target: { value: "print(5)" } });
    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "cpp" } });
    // Each language keeps its own draft.
    expect(editor().value).toBe("");
    fireEvent.change(editor(), { target: { value: "int main(){}" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(submitMutate).toHaveBeenLastCalledWith({ language: "cpp", source: "int main(){}", kind: "submit" });
    fireEvent.click(screen.getByRole("button", { name: "Run examples" }));
    expect(submitMutate).toHaveBeenLastCalledWith({ language: "cpp", source: "int main(){}", kind: "run" });
  });

  it("keeps the draft, language and tab across visits", () => {
    const first = page();
    writeTab();
    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "cpp" } });
    fireEvent.change(editor(), { target: { value: "// mine" } });
    first.unmount();
    page();
    // Back on the Write tab without asking: the choice is remembered.
    expect(screen.getByRole("tab", { name: "Write code" })).toHaveAttribute("aria-selected", "true");
    expect((screen.getByLabelText("Language") as HTMLSelectElement).value).toBe("cpp");
    expect(editor().value).toBe("// mine");
  });

  it("shows the queue position while waiting", () => {
    judgings = [judging({ status: "queued", verdict: null, queue_position: 3, tests_total: null })];
    page();
    expect(screen.getByText("Waiting to be judged — 3 in line")).toBeInTheDocument();
  });

  it("shows a failing example with its input, expected and actual output", () => {
    judgings = [
      judging({
        verdict: "wrong_answer",
        tests_passed: 0,
        tests: [{ index: 0, sample: true, verdict: "wrong_answer", time_ms: 5, memory_kb: 900, output: "4\n" }],
      }),
    ];
    page();
    expect(screen.getAllByText("Wrong answer").length).toBeGreaterThan(0);
    expect(screen.getByText("Example 1: Wrong answer.")).toBeInTheDocument();
    expect(screen.getByText("Your output")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("names a failing hidden test without its data", () => {
    judgings = [
      judging({
        verdict: "time_limit",
        tests_passed: 1,
        tests: [
          { index: 0, sample: true, verdict: "accepted", time_ms: 5, memory_kb: 900, output: "5\n" },
          { index: 1, sample: false, verdict: "time_limit", time_ms: null, memory_kb: null, output: null },
        ],
      }),
    ];
    page();
    expect(
      screen.getByText("Hidden test 2: Time limit exceeded. Its data stays hidden."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Your output")).toBeNull();
  });

  it("never shows example data for a hidden test, even if indices line up", () => {
    // An example added after this judging: hidden test 2 now shares an index
    // with example 2 — the page must still treat it as hidden.
    problem = {
      ...problem,
      examples: [...problem.examples, { index: 1, input: "7 7\n", answer: "14\n", truncated: false }],
    };
    judgings = [
      judging({
        verdict: "wrong_answer",
        tests: [
          { index: 0, sample: true, verdict: "accepted", time_ms: 5, memory_kb: 900, output: "5\n" },
          { index: 1, sample: false, verdict: "wrong_answer", time_ms: null, memory_kb: null, output: null },
        ],
      }),
    ];
    page();
    expect(screen.getByText("Hidden test 2: Wrong answer. Its data stays hidden.")).toBeInTheDocument();
    expect(screen.queryByText("Your output")).toBeNull();
  });

  it("shows the compiler's messages on a compilation error", () => {
    judgings = [judging({ verdict: "compile_error", compile_output: "main.cpp:1: error: x", tests_total: 3, tests_passed: 0 })];
    page();
    expect(screen.getByText("main.cpp:1: error: x")).toBeInTheDocument();
  });

  it("explains when the judge is down, and won't submit", () => {
    problem = { ...problem, judge_ready: false };
    page();
    writeTab();
    fireEvent.change(editor(), { target: { value: "print(5)" } });
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("isn't running right now");
  });

  it("sends a flag challenge back to the board", () => {
    theChallenge = { ...challenge, flag_type: "static" };
    page();
    expect(screen.getByText(/solved with a flag/)).toBeInTheDocument();
  });
});


describe("uploading a file (the default)", () => {
  const upload = (file: File) =>
    fireEvent.change(screen.getByLabelText("Choose file"), { target: { files: [file] } });

  it("opens on the upload tab and asks for a file before running", () => {
    page();
    expect(screen.getByRole("tab", { name: "Upload a file" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Drop your solution file here")).toBeInTheDocument();
    expect(screen.getByText(/\.py, \.cpp/)).toBeInTheDocument();
    expect(screen.getByText(/Choose your solution file/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
    expect(screen.queryByLabelText("Your solution")).toBeNull(); // no editor here
  });

  it("submits exactly the chosen file, in the language its extension names", async () => {
    // A stale browser draft must not be what gets sent.
    window.localStorage.setItem("flagpost.code.c1.ch1", JSON.stringify({ language: "python3", sources: { cpp: "old" } }));
    page();
    upload(new File(["int main() { return 0; }\n"], "main.cc", { type: "text/plain" }));
    expect(await screen.findByText("main.cc")).toBeInTheDocument();
    expect(screen.getByText("C++ · 1 line · 0.1 KB")).toBeInTheDocument();
    expect((screen.getByLabelText("Language") as HTMLSelectElement).value).toBe("cpp");
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(submitMutate).toHaveBeenLastCalledWith({
      language: "cpp",
      source: "int main() { return 0; }\n",
      kind: "submit",
    });
  });

  it("takes a file dropped on the drop zone", async () => {
    page();
    const zone = screen.getByText("Drop your solution file here").closest("div.border-dashed")!;
    const file = new File(["print(5)\n"], "solution.py", { type: "text/x-python" });
    fireEvent.drop(zone, { dataTransfer: { files: [file], types: ["Files"] } });
    expect(await screen.findByText("solution.py")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run examples" }));
    expect(submitMutate).toHaveBeenLastCalledWith({ language: "python3", source: "print(5)\n", kind: "run" });
  });

  it("opens an uploaded file in the browser editor", async () => {
    page();
    upload(new File(["print(1)\n"], "s.py"));
    await screen.findByText("s.py");
    fireEvent.click(screen.getByRole("button", { name: "Edit in the browser" }));
    expect(screen.getByRole("tab", { name: "Write code" })).toHaveAttribute("aria-selected", "true");
    expect(editor().value).toBe("print(1)\n");
  });

  it("loads a file dropped onto the browser editor", async () => {
    page();
    writeTab();
    const zone = editor().parentElement!;
    fireEvent.drop(zone, { dataTransfer: { files: [new File(["print(7)"], "x.py")], types: ["Files"] } });
    expect(await screen.findByText("Loaded x.py.")).toBeInTheDocument();
    expect(editor().value).toBe("print(7)");
  });

  it("refuses a file that's too big or isn't text", async () => {
    page();
    upload(new File(["x".repeat(129 * 1024)], "big.py"));
    expect(await screen.findByRole("alert")).toHaveTextContent("too big");
    upload(new File([new Uint8Array([0xff, 0xfe, 0x00, 0x81])], "a.out"));
    expect(await screen.findByText(/isn't plain text/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  });

  it("says so when the file can't be read, rather than blaming its contents", async () => {
    page();
    const file = new File(["print(1)"], "s.py");
    Object.defineProperty(file, "arrayBuffer", { value: () => Promise.reject(new Error("denied")) });
    upload(file);
    expect(await screen.findByText(/couldn't be read/)).toBeInTheDocument();
  });

  it("warns when the file type matches none of the problem's languages", async () => {
    page();
    upload(new File(["fn main() {}"], "main.rs"));
    expect(await screen.findByText(/check the language/)).toBeInTheDocument();
    // Kept the chosen language; the file is still loaded so it can be sent as-is.
    expect((screen.getByLabelText("Language") as HTMLSelectElement).value).toBe("python3");
    expect(screen.getByText("main.rs")).toBeInTheDocument();
  });
});

describe("languageForFile", () => {
  const langs = [
    { key: "python3", extension: ".py" },
    { key: "pypy3", extension: ".py" },
    { key: "cpp", extension: ".cpp" },
  ];
  it("matches extensions and their common spellings", () => {
    expect(languageForFile("a.cpp", langs, "python3")).toBe("cpp");
    expect(languageForFile("A.CXX", langs, "python3")).toBe("cpp");
    expect(languageForFile("noext", langs, "python3")).toBeNull();
    expect(languageForFile("x.go", langs, "python3")).toBeNull();
  });
  it("keeps the current language when it also fits (Python vs PyPy)", () => {
    expect(languageForFile("s.py", langs, "pypy3")).toBe("pypy3");
    expect(languageForFile("s.py", langs, "cpp")).toBe("python3");
  });
});
