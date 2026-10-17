import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BackupPanel } from "@/components/admin/backup-panel";
import { renderWithIntl } from "@/test/intl";

// The backend offers each direction only the sections the viewer's grants
// allow (GHSA-3r5x); an uploaded file can carry more than that — an
// Administrator's full backup in a delegate's hands. The import checklist must
// offer and pre-select only the allowed intersection, or the import 403s.
const mockImport = vi.fn();
vi.mock("@/lib/hooks/use-site-settings", () => ({
  useBackupSections: (direction: "export" | "import") => ({
    data: direction === "export" ? ["site_settings"] : ["site_settings", "users"],
  }),
  useExportBackup: () => ({ mutate: vi.fn(), isPending: false }),
  useImportBackup: () => ({ mutate: mockImport, isPending: false }),
}));
vi.mock("@/components/ui/confirm", () => ({
  useConfirm: () => () => Promise.resolve(true),
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

function pickBackup(sections: string[]) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  const doc = { flagpost_export: true, schema_version: 1, sections, data: {} };
  const file = new File([JSON.stringify(doc)], "backup.json", { type: "application/json" });
  fireEvent.change(input, { target: { files: [file] } });
}

describe("BackupPanel import", () => {
  afterEach(() => vi.clearAllMocks());

  it("offers only the file's sections the viewer may import", async () => {
    renderWithIntl(<BackupPanel />);
    pickBackup(["site_settings", "users", "audit_log"]);

    const users = await screen.findByRole("checkbox", { name: "User accounts" });
    expect(users).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "Audit log" })).not.toBeInTheDocument();
    expect(screen.getByText(/beyond your permissions: Audit log/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Import selected" }));
    await waitFor(() => expect(mockImport).toHaveBeenCalled());
    expect(mockImport.mock.calls[0][0].sections).toEqual(["site_settings", "users"]);
  });
});
