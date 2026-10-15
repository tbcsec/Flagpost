import { fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { ProblemPackageActions } from "@/components/challenges/problem-packages";
import type { PackageImportResult } from "@/lib/types";

// Importing ICPC/Kattis problem packages (#451).

let moduleEnabled: boolean;
const importPackages = vi.fn();
const exportAll = vi.fn();

vi.mock("@/lib/hooks/use-judge", () => ({
  useJudgeStatus: () => ({
    data: { module_enabled: moduleEnabled, judge_enabled: true, ready: true, languages: [], default_time_limit_ms: 2000 },
  }),
  useImportProblemPackages: () => ({ mutate: importPackages, isPending: false, isError: false }),
  useExportProblemPackages: () => ({ mutate: exportAll, isPending: false }),
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

beforeEach(() => {
  moduleEnabled = true;
});
afterEach(() => {
  importPackages.mockReset();
  exportAll.mockReset();
});

const report: PackageImportResult = {
  created: [{ name: "Sum of Two", challenge_id: "c9", tests: 3, warnings: ["The package doesn't set a time limit."] }],
  skipped: [{ name: "Hello", reason: "A challenge with this title already exists" }],
  refused: [{ name: "guess", reason: "It's a interactive problem" }],
};

describe("ProblemPackageActions", () => {
  it("isn't offered without the code judge", () => {
    moduleEnabled = false;
    const { container } = renderWithIntl(
      <ProblemPackageActions competitionId="c1" hasProgramming onOpen={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("imports a package with the form's time limit, then reports what happened", () => {
    const onOpen = vi.fn();
    importPackages.mockImplementation((_input, opts) => opts.onSuccess(report));
    renderWithIntl(<ProblemPackageActions competitionId="c1" hasProgramming={false} onOpen={onOpen} />);
    expect(screen.queryByRole("button", { name: "Export problem packages" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Import problem package…" }));
    // Pre-filled with the site default.
    expect(screen.getByLabelText(/Time limit for problems/)).toHaveValue(2);
    const file = new File(["zip"], "sum.zip", { type: "application/zip" });
    fireEvent.change(screen.getByLabelText("Package file"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(importPackages.mock.calls[0][0]).toEqual({ file, defaultTimeLimitMs: 2000 });

    expect(screen.getByText("1 problem imported as a draft")).toBeInTheDocument();
    expect(screen.getByText("The package doesn't set a time limit.")).toBeInTheDocument();
    expect(screen.getByText(/interactive problem/)).toBeInTheDocument();
    expect(screen.getByText(/already exists/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sum of Two" }));
    expect(onOpen).toHaveBeenCalledWith("c9");
  });

  it("exports every programming problem", () => {
    renderWithIntl(<ProblemPackageActions competitionId="c1" hasProgramming onOpen={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Export problem packages" }));
    expect(exportAll).toHaveBeenCalled();
  });
});
