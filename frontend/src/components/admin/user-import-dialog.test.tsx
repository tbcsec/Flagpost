import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UserImportDialog } from "@/components/admin/user-import-dialog";
import type { UserImportReport, UserImportRow } from "@/lib/types";

// The dialog drives one mutation (both phases) plus the competitions list for
// the default-competition selector — mock both so the tests exercise pure
// preview/confirm behaviour (#171).
const mockMutateAsync = vi.fn();
vi.mock("@/lib/hooks/use-users", () => ({
  useImportUsers: () => ({ mutateAsync: mockMutateAsync, isPending: false }),
}));
vi.mock("@/lib/hooks/use-competitions", () => ({
  useCompetitions: () => ({ data: [{ id: "comp-1", name: "Spring CTF" }] }),
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

function row(overrides: Partial<UserImportRow> = {}): UserImportRow {
  return {
    row: 2,
    display_name: "alice",
    email: "alice@example.com",
    role: null,
    competition: null,
    status: "create",
    reason: null,
    role_action: null,
    role_reason: null,
    ...overrides,
  };
}

function report(overrides: Partial<UserImportReport> = {}): UserImportReport {
  return {
    dry_run: true,
    total: 1,
    created: 1,
    skipped: 0,
    errors: 0,
    roles_assigned: 0,
    roles_skipped: 0,
    ignored_columns: [],
    rows: [row()],
    ...overrides,
  };
}

function pickFile() {
  const input = document.getElementById("user-import-file") as HTMLInputElement;
  const file = new File(["display_name,password\nalice,secret123\n"], "users.csv", {
    type: "text/csv",
  });
  fireEvent.change(input, { target: { files: [file] } });
}

describe("UserImportDialog", () => {
  afterEach(() => vi.clearAllMocks());

  it("dry-runs the picked file and renders the per-row preview", async () => {
    mockMutateAsync.mockResolvedValue(
      report({
        total: 3,
        created: 1,
        skipped: 1,
        errors: 1,
        rows: [
          row(),
          row({ row: 3, display_name: "bob", status: "skip", reason: "already exists" }),
          row({ row: 4, display_name: "eve", status: "error", reason: "invalid email address" }),
        ],
      }),
    );
    render(<UserImportDialog open onOpenChange={() => {}} />);
    pickFile();

    await waitFor(() => expect(screen.getByText("will create")).toBeInTheDocument());
    expect(mockMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ dryRun: true }),
    );
    expect(screen.getByText(/Preview: 1 to create, 1 skipped, 1 error/)).toBeInTheDocument();
    expect(screen.getByText("skip: already exists")).toBeInTheDocument();
    expect(screen.getByText("error: invalid email address")).toBeInTheDocument();
  });

  it("surfaces a skipped role as a warning on a created row", async () => {
    mockMutateAsync.mockResolvedValue(
      report({
        roles_skipped: 1,
        rows: [row({ role: "Judge", role_action: "skip", role_reason: "you don't hold manage_roles" })],
      }),
    );
    render(<UserImportDialog open onOpenChange={() => {}} />);
    pickFile();

    await waitFor(() =>
      expect(screen.getByText(/skipped: you don't hold manage_roles/)).toBeInTheDocument(),
    );
  });

  it("confirm re-posts without dry_run and shows the final report", async () => {
    mockMutateAsync
      .mockResolvedValueOnce(report()) // the preview
      .mockResolvedValueOnce(report({ dry_run: false })); // the commit
    render(<UserImportDialog open onOpenChange={() => {}} />);
    pickFile();
    await waitFor(() => expect(screen.getByText(/Confirm import/)).toBeEnabled());

    fireEvent.click(screen.getByText(/Confirm import/));
    await waitFor(() => expect(screen.getByText("created")).toBeInTheDocument());
    expect(mockMutateAsync).toHaveBeenLastCalledWith(
      expect.objectContaining({ dryRun: false }),
    );
    expect(screen.getByText(/Done: 1 created/)).toBeInTheDocument();
  });

  it("keeps confirm disabled when the preview has nothing to do", async () => {
    mockMutateAsync.mockResolvedValue(
      report({
        created: 0,
        skipped: 1,
        rows: [row({ status: "skip", reason: "already exists" })],
      }),
    );
    render(<UserImportDialog open onOpenChange={() => {}} />);
    pickFile();

    await waitFor(() => expect(screen.getByText(/skip: already exists/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Confirm import/ })).toBeDisabled();
  });
});
