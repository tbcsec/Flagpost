import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import AdminIndex from "@/app/(app)/admin/page";
import AdminAutomationsPage from "@/app/(app)/admin/automations/page";
import AdminCompetitionsPage from "@/app/(app)/admin/competitions/page";
import AdminRolesPage from "@/app/(app)/admin/roles/page";
import AdminSettingsPage from "@/app/(app)/admin/settings/page";
import AdminUsersPage from "@/app/(app)/admin/users/page";

// #477 opened the Admin section to any global delegate, so each page decides
// for itself whether the viewer may use it — and fires none of its queries
// when they may not, rather than rendering actions that would only 403.

let ready = true;
let grants: string[] = [];
vi.mock("@/lib/hooks/use-permissions", () => ({
  useAccess: () => ({
    ready,
    has: (p: string) => grants.includes(p),
    hasGlobal: (p: string) => grants.includes(p),
  }),
}));

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/admin/settings",
  useSearchParams: () => new URLSearchParams(),
}));

const COMPETITION = {
  id: "c1",
  name: "Spring CTF",
  participation_mode: "team",
  visibility: "private",
  archived_at: null,
  purge_after: null,
};
let competitions: unknown[] = [];
const useCompetitions = vi.fn(() => ({
  data: competitions,
  isLoading: false,
  isError: false,
  error: null,
}));
vi.mock("@/lib/hooks/use-competitions", () => ({
  useCompetitions: () => useCompetitions(),
  useArchiveCompetition: () => ({ mutate: vi.fn(), isPending: false }),
  useCloneCompetition: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteCompetition: () => ({ mutate: vi.fn(), isPending: false }),
}));
const useOperationalSettings = vi.fn((_enabled: boolean) => ({ data: undefined, isLoading: false }));
vi.mock("@/lib/hooks/use-site-settings", () => ({
  useSiteSettings: () => ({ data: undefined }),
  useOperationalSettings: (enabled: boolean) => useOperationalSettings(enabled),
  useUpdateOperationalSettings: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/components/competitions/create-competition-dialog", () => ({
  CreateCompetitionDialog: () => <button type="button">New competition</button>,
}));

const RULE = {
  id: "r1",
  name: "Welcome mail",
  trigger_type: "user.registered",
  conditions: [],
  actions: [{ type: "send_email" }],
  is_enabled: true,
  trigger_count: 0,
  last_triggered_at: null,
};
let rules: unknown[] = [];
const useAutomations = vi.fn(() => ({ data: rules, isLoading: false }));
vi.mock("@/lib/hooks/use-automations", () => ({
  useAutomationCatalog: () => ({ data: { triggers: [], actions: [] } }),
  useAutomations: () => useAutomations(),
  useCreateAutomation: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateAutomation: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteAutomation: () => ({ mutate: vi.fn() }),
  useToggleAutomation: () => ({ toggle: vi.fn() }),
}));
vi.mock("@/components/automations/rule-builder", () => ({ RuleBuilder: () => null }));
vi.mock("@/components/ui/confirm", () => ({ useConfirm: () => () => Promise.resolve(true) }));

let directory: { id: string; display_name: string; email: string | null }[] = [];
const useUsers = vi.fn((_q: string, _opts?: { enabled?: boolean }) => ({
  data: directory,
  isLoading: false,
}));
vi.mock("@/lib/hooks/use-users", () => ({
  useUsers: (q: string, opts?: { enabled?: boolean }) => useUsers(q, opts),
  useBanUser: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteUser: () => ({ mutate: vi.fn(), isPending: false }),
  useRemoveUserAvatar: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/components/admin/api-tokens-panel", () => ({
  ApiTokensPanel: () => <div>Token oversight panel</div>,
}));
vi.mock("@/components/admin/user-form-dialog", () => ({ UserFormDialog: () => null }));
vi.mock("@/components/admin/user-import-dialog", () => ({ UserImportDialog: () => null }));

const ROLE = {
  id: "role-1",
  name: "Auditor",
  description: "Reads the event log",
  scope: "global",
  is_system: false,
  permissions: ["view_audit_log"],
};
const assignRole = vi.fn();
const useRoles = vi.fn(() => ({ data: [ROLE], isLoading: false }));
vi.mock("@/lib/hooks/use-roles", () => ({
  useRoles: () => useRoles(),
  useRoleCatalog: () => ({ data: [], isLoading: false }),
  useRoleAssignments: () => ({ data: [] }),
  useAssignRole: () => ({ mutate: assignRole, isPending: false }),
  useUnassignRole: () => ({ mutate: vi.fn() }),
  useCreateRole: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateRole: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteRole: () => ({ mutate: vi.fn(), isPending: false }),
}));

// Settings: each panel stands in for itself, so a test reads which mounted.
vi.mock("@/components/admin/ai-settings-panel", () => ({ AiSettingsPanel: () => <div>AI panel</div> }));
vi.mock("@/components/admin/appearance-panel", () => ({
  AppearancePanel: () => <div>Appearance panel</div>,
}));
vi.mock("@/components/admin/instances-settings-panel", () => ({
  InstancesSettingsPanel: () => <div>Instances panel</div>,
}));
vi.mock("@/components/admin/judge-settings-panel", () => ({
  JudgeSettingsPanel: () => <div>Judge panel</div>,
}));
vi.mock("@/components/admin/auth-providers-panel", () => ({
  AuthProvidersPanel: () => <div>Auth panel</div>,
}));
vi.mock("@/components/admin/backup-panel", () => ({ BackupPanel: () => <div>Backup panel</div> }));
vi.mock("@/components/admin/rules-settings-panel", () => ({
  RulesSettingsPanel: () => <div>Rules panel</div>,
}));

afterEach(() => {
  ready = true;
  grants = [];
  directory = [];
  competitions = [];
  rules = [];
  vi.clearAllMocks();
});

describe("/admin", () => {
  it("lands a narrow delegate on the page their grant opens", () => {
    grants = ["view_audit_log"];
    renderWithIntl(<AdminIndex />);
    expect(replace).toHaveBeenCalledWith("/admin/events");
  });

  it("lands an administrator on the dashboard", () => {
    grants = ["view_global_analytics", "view_audit_log", "manage_roles"];
    renderWithIntl(<AdminIndex />);
    expect(replace).toHaveBeenCalledWith("/admin/dashboard");
  });

  it("waits for permissions before going anywhere", () => {
    ready = false;
    grants = ["view_audit_log"];
    renderWithIntl(<AdminIndex />);
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("Admin → Competitions", () => {
  it("is no-access, with no query, without a competition grant", () => {
    grants = ["view_audit_log"];
    renderWithIntl(<AdminCompetitionsPage />);
    expect(screen.getByText("No access")).toBeInTheDocument();
    expect(screen.queryByText("New competition")).toBeNull();
    expect(useCompetitions).not.toHaveBeenCalled();
  });

  it("offers every action to an administrator", () => {
    grants = ["create_competition", "edit_competition", "delete_competition"];
    competitions = [COMPETITION];
    renderWithIntl(<AdminCompetitionsPage />);
    expect(screen.getByText("New competition")).toBeInTheDocument();
    for (const name of ["Clone", "Archive", "Delete"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("offers an archiver only archiving", () => {
    grants = ["edit_competition"];
    competitions = [COMPETITION];
    renderWithIntl(<AdminCompetitionsPage />);
    expect(screen.getByText("Spring CTF")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(screen.queryByText("New competition")).toBeNull();
    expect(screen.queryByRole("button", { name: "Clone" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("offers a deleter only deletion", () => {
    grants = ["delete_competition"];
    competitions = [COMPETITION];
    renderWithIntl(<AdminCompetitionsPage />);
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Clone" })).toBeNull();
  });
});

describe("Admin → Automations", () => {
  it("is no-access, with no query, without a global automation_view", () => {
    grants = ["manage_pages"];
    renderWithIntl(<AdminAutomationsPage />);
    expect(screen.getByText("No access")).toBeInTheDocument();
    expect(useAutomations).not.toHaveBeenCalled();
  });

  it("lists global rules read-only for automation_view alone", () => {
    grants = ["automation_view"];
    rules = [RULE];
    renderWithIntl(<AdminAutomationsPage />);
    expect(screen.getByText("Welcome mail")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /New global rule/ })).toBeNull();
    for (const name of ["Edit", "Disable", "Delete"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it("offers a new global rule to a creator", () => {
    grants = ["automation_view", "automation_create"];
    renderWithIntl(<AdminAutomationsPage />);
    expect(screen.getByRole("button", { name: /New global rule/ })).toBeInTheDocument();
  });

  it("offers editing, toggling and deleting to an editor", () => {
    grants = ["automation_view", "automation_edit"];
    rules = [RULE];
    renderWithIntl(<AdminAutomationsPage />);
    for (const name of ["Edit", "Disable", "Delete"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });
});

describe("Admin → Users", () => {
  it("is no-access, with no query, without a users or tokens grant", () => {
    grants = ["manage_users"];
    renderWithIntl(<AdminUsersPage />);
    expect(screen.getByText("No access")).toBeInTheDocument();
    expect(useUsers).not.toHaveBeenCalled();
  });

  it("shows token oversight alone to a tokens-only delegate", () => {
    grants = ["manage_api_tokens"];
    renderWithIntl(<AdminUsersPage />);
    expect(screen.getByText("Token oversight panel")).toBeInTheDocument();
    expect(screen.queryByText("No access")).toBeNull();
    expect(useUsers).not.toHaveBeenCalled();
  });

  it("shows the directory, and tokens alongside it, to a holder of both", () => {
    grants = ["view_all_users", "manage_api_tokens"];
    renderWithIntl(<AdminUsersPage />);
    expect(useUsers).toHaveBeenCalled();
    expect(screen.getByText("Token oversight panel")).toBeInTheDocument();
  });
});

describe("Admin → Roles", () => {
  it("is no-access, with no query, without manage_roles", () => {
    grants = ["view_audit_log"];
    renderWithIntl(<AdminRolesPage />);
    expect(screen.getByText(/don't have access to role management/)).toBeInTheDocument();
    expect(useRoles).not.toHaveBeenCalled();
    expect(useUsers).not.toHaveBeenCalled();
  });

  it("assigns by a typed username when the directory is out of reach", () => {
    grants = ["manage_roles"];
    renderWithIntl(<AdminRolesPage />);
    // The picker would read the directory (view_all_users) — never asked for.
    expect(useUsers).toHaveBeenCalledWith("", { enabled: false });
    fireEvent.change(screen.getByPlaceholderText("Username or email"), {
      target: { value: "  alice  " },
    });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "role-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    expect(assignRole).toHaveBeenCalledWith(
      { email: "alice", role_id: "role-1", competition_id: null },
      expect.anything(),
    );
  });

  it("picks from the directory for a holder of view_all_users", () => {
    grants = ["manage_roles", "view_all_users"];
    renderWithIntl(<AdminRolesPage />);
    expect(useUsers).toHaveBeenCalledWith("", { enabled: true });
    expect(screen.queryByPlaceholderText("Username or email")).toBeNull();
  });

  it("assigns a picked account by its id, not an identifier", () => {
    // An identifier could resolve to a different account whose email reads
    // like the picked username; the id can't.
    grants = ["manage_roles", "view_all_users"];
    directory = [{ id: "u-7", display_name: "boss@corp.example", email: null }];
    renderWithIntl(<AdminRolesPage />);
    fireEvent.focus(screen.getByLabelText("User"));
    fireEvent.mouseDown(screen.getByRole("option", { name: /boss@corp\.example/ }));
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "role-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    expect(assignRole).toHaveBeenCalledWith(
      { user_id: "u-7", role_id: "role-1", competition_id: null },
      expect.anything(),
    );
  });
});

describe("Admin → Site settings", () => {
  it("mounts only the auth tab for an auth-providers delegate", () => {
    grants = ["manage_auth_providers"];
    renderWithIntl(<AdminSettingsPage />);
    expect(screen.getByText("Auth panel")).toBeInTheDocument();
    // The general panels read endpoints gated on manage_site_settings; they
    // aren't mounted (not merely hidden), so nothing fires and 403s.
    for (const panel of ["Rules panel", "Backup panel", "Appearance panel", "AI panel"]) {
      expect(screen.queryByText(panel)).toBeNull();
    }
    expect(useOperationalSettings).toHaveBeenCalledWith(false);
  });

  it("mounts the general panels for manage_site_settings", () => {
    grants = ["manage_site_settings"];
    renderWithIntl(<AdminSettingsPage />);
    for (const panel of ["Rules panel", "Backup panel", "Appearance panel"]) {
      expect(screen.getByText(panel)).toBeInTheDocument();
    }
    expect(screen.queryByText("Auth panel")).toBeNull();
    expect(useOperationalSettings).toHaveBeenCalledWith(true);
  });
});
