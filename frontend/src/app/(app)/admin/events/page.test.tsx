import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import AdminEventLogPage from "@/app/(app)/admin/events/page";
import type { AuditLogEntry } from "@/lib/types";

// The page is a filter form over four lookup hooks plus the log query — mock
// them all so the tests drive pure expand/collapse behaviour: the full payload
// opens in its own full-width row under the entry, never inside the
// width-constrained Payload column (#157 follow-up).
const mockUseAuditLog = vi.fn();
vi.mock("@/lib/hooks/use-audit-log", () => ({
  useAuditEventNames: () => ({ data: [] }),
  useAuditLog: (...args: unknown[]) => mockUseAuditLog(...args),
}));
vi.mock("@/lib/hooks/use-competitions", () => ({
  useCompetitions: () => ({ data: [{ id: "c1", name: "Spring CTF" }] }),
}));
vi.mock("@/lib/hooks/use-teams", () => ({ useTeams: () => ({ data: [] }) }));
const mockUseUsers = vi.fn((..._args: unknown[]) => ({ data: [] }));
vi.mock("@/lib/hooks/use-users", () => ({
  useUsers: (...args: unknown[]) => mockUseUsers(...args),
}));
// The page gates itself on view_audit_log (#477); the actor picker needs the
// user directory (view_all_users). Grants are swapped per test.
let grants: string[] = ["view_audit_log", "view_all_users"];
vi.mock("@/lib/hooks/use-permissions", () => ({
  useAccess: () => ({ ready: true, hasGlobal: (p: string) => grants.includes(p) }),
}));

function entry(id: string, overrides: Partial<AuditLogEntry> = {}): AuditLogEntry {
  return {
    id,
    event_name: "user.created",
    payload: { user_id: `subject-${id}`, actor_user_id: "admin-1" },
    competition_id: "c1",
    user_id: "admin-1",
    created_at: "2026-08-09T12:00:00Z",
    ...overrides,
  };
}

function renderPage(items: AuditLogEntry[]) {
  mockUseAuditLog.mockReturnValue({
    data: { items, total: items.length, limit: 25, offset: 0 },
    isLoading: false,
    isError: false,
  });
  return renderWithIntl(<AdminEventLogPage />);
}

const toggleRow = (id: string) =>
  screen.getByText(`{"user_id":"subject-${id}","actor_user_id":"admin-1"}`).closest("tr")!;

describe("AdminEventLogPage payload expansion", () => {
  afterEach(() => vi.clearAllMocks());

  it("collapsed rows show only the one-line preview, no pretty payload", () => {
    renderPage([entry("e1")]);
    expect(
      screen.getByText('{"user_id":"subject-e1","actor_user_id":"admin-1"}'),
    ).toBeInTheDocument();
    expect(document.querySelector("pre")).toBeNull();
    expect(toggleRow("e1")).toHaveAttribute("aria-expanded", "false");
  });

  it("clicking a row opens the full payload in its own full-width row", () => {
    renderPage([entry("e1")]);
    fireEvent.click(toggleRow("e1"));

    const pre = document.querySelector("pre")!;
    expect(pre).not.toBeNull();
    // Pretty-printed (multi-line), not the compact preview.
    expect(pre.textContent).toContain('"user_id": "subject-e1"');
    // Its own detail row spanning every column — full table width.
    const cell = pre.closest("td")!;
    expect(cell.getAttribute("colspan")).toBe("4");
    expect(cell.closest("tr")).not.toBe(toggleRow("e1"));
    expect(toggleRow("e1")).toHaveAttribute("aria-expanded", "true");
    // The one-line preview stays put in the entry row.
    expect(
      screen.getByText('{"user_id":"subject-e1","actor_user_id":"admin-1"}'),
    ).toBeInTheDocument();
  });

  it("clicking again collapses, and expanding another row moves the detail", () => {
    renderPage([entry("e1"), entry("e2")]);
    fireEvent.click(toggleRow("e1"));
    fireEvent.click(toggleRow("e1"));
    expect(document.querySelector("pre")).toBeNull();

    // Single-expansion: opening e2 after e1 leaves exactly one detail row.
    fireEvent.click(toggleRow("e1"));
    fireEvent.click(toggleRow("e2"));
    const pres = document.querySelectorAll("pre");
    expect(pres).toHaveLength(1);
    expect(pres[0].textContent).toContain('"user_id": "subject-e2"');
  });

  it("clicking inside the open payload row does not collapse it", () => {
    renderPage([entry("e1")]);
    fireEvent.click(toggleRow("e1"));
    fireEvent.click(document.querySelector("pre")!);
    expect(document.querySelector("pre")).not.toBeNull();
  });

  it("toggles from the keyboard (Enter and Space) — rows are focusable", () => {
    renderPage([entry("e1")]);
    const row = toggleRow("e1");
    expect(row).toHaveAttribute("tabindex", "0");

    fireEvent.keyDown(row, { key: "Enter" });
    expect(document.querySelector("pre")).not.toBeNull();
    fireEvent.keyDown(row, { key: " " });
    expect(document.querySelector("pre")).toBeNull();
    // Other keys don't toggle.
    fireEvent.keyDown(row, { key: "ArrowDown" });
    expect(document.querySelector("pre")).toBeNull();
  });

  it("links the toggle row to its payload row via aria-controls", () => {
    renderPage([entry("e1")]);
    const row = toggleRow("e1");
    expect(row).not.toHaveAttribute("aria-controls");

    fireEvent.click(row);
    const controls = row.getAttribute("aria-controls")!;
    expect(controls).toBeTruthy();
    expect(document.getElementById(controls)).toBe(
      document.querySelector("pre")!.closest("td"),
    );
  });
});

// #477: the Admin section opens for any global delegate, so the page decides.
describe("AdminEventLogPage access", () => {
  afterEach(() => {
    vi.clearAllMocks();
    grants = ["view_audit_log", "view_all_users"];
  });

  it("shows no-access, and never queries the log, without view_audit_log", () => {
    grants = ["manage_pages"];
    renderPage([entry("e1")]);
    expect(screen.getByText("No access")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Search event name or payload…")).toBeNull();
    expect(mockUseAuditLog).not.toHaveBeenCalled();
    expect(mockUseUsers).not.toHaveBeenCalled();
  });

  it("filters by a pasted user id when the viewer can't read the directory", () => {
    grants = ["view_audit_log"];
    renderPage([entry("e1")]);
    // The directory query is switched off rather than left to 403…
    expect(mockUseUsers).toHaveBeenCalledWith("", { enabled: false });
    // …and the actor filter is a plain id field.
    expect(screen.getByPlaceholderText("Paste a user id")).toBeInTheDocument();
  });

  it("keeps the actor picker for a viewer with the directory", () => {
    renderPage([entry("e1")]);
    expect(mockUseUsers).toHaveBeenCalledWith("", { enabled: true });
    expect(screen.queryByPlaceholderText("Paste a user id")).toBeNull();
  });
});
