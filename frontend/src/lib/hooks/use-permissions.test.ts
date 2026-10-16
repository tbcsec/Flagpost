import { describe, expect, it } from "vitest";

import { GLOBAL_SCOPE_PERMISSIONS } from "@/lib/admin-surfaces";
import { deriveAccess } from "@/lib/hooks/use-permissions";

// The shell's two big switches: whether the Admin section exists (isAdmin) and
// whether the viewer belongs in the lobby (inLobby). #477 broadened the first to
// any global grant that opens an Admin page — which must not drag a narrow
// delegate out of the lobby onto competition pages that would only 403.

const ADMIN_GLOBAL = [
  "challenge_view", "create_competition", "manage_users", "manage_roles",
  "view_all_users", "view_audit_log", "view_global_analytics", "manage_site_settings",
];

describe("deriveAccess", () => {
  it("is not ready, and conservative, until permissions load", () => {
    const a = deriveAccess(undefined, null);
    expect(a.ready).toBe(false);
    expect(a.isAdmin).toBe(false);
  });

  it("an administrator opens Admin and never sits in the lobby", () => {
    const a = deriveAccess({ global: ADMIN_GLOBAL, by_competition: {} }, null);
    expect(a.isAdmin).toBe(true);
    expect(a.inLobby).toBe(false);
  });

  it("a narrow global delegate opens Admin but stays in the lobby", () => {
    const a = deriveAccess({ global: ["view_audit_log"], by_competition: {} }, null);
    expect(a.isAdmin).toBe(true);
    // No membership and only global-scope grants: competition pages would 403.
    expect(a.inLobby).toBe(true);
  });

  it("every global-scope grant together still leaves a delegate in the lobby", () => {
    const a = deriveAccess({ global: [...GLOBAL_SCOPE_PERMISSIONS], by_competition: {} }, null);
    expect(a.isAdmin).toBe(true);
    expect(a.inLobby).toBe(true);
  });

  it("a competition-scope grant held globally takes a delegate out of the lobby", () => {
    // A custom global role can carry competition-scope grants, which then hold
    // in every competition — ticket moderation site-wide, say, with no
    // challenge_view. Sending them to the lobby would lock them out of it.
    const a = deriveAccess(
      { global: ["manage_users", "ticket_view", "edit_competition"], by_competition: {} },
      null,
    );
    expect(a.inLobby).toBe(false);
  });

  it("a delegate who has joined a competition leaves the lobby", () => {
    const a = deriveAccess(
      { global: ["view_audit_log"], by_competition: { c1: ["challenge_view"] } },
      "c1",
    );
    expect(a.isAdmin).toBe(true);
    expect(a.inLobby).toBe(false);
  });

  it("a new user with nothing is in the lobby with no Admin", () => {
    const a = deriveAccess({ global: [], by_competition: {} }, null);
    expect(a.isAdmin).toBe(false);
    expect(a.inLobby).toBe(true);
  });

  it("competition-scoped grants never open the global Admin section", () => {
    // A judge holds automation_view and view_competition_analytics in their
    // competition — and Admin → Automations needs a *global* automation_view.
    const judge = deriveAccess(
      { global: [], by_competition: { c1: ["automation_view", "challenge_edit", "challenge_view"] } },
      "c1",
    );
    expect(judge.has("automation_view")).toBe(true);
    expect(judge.hasGlobal("automation_view")).toBe(false);
    expect(judge.isAdmin).toBe(false);
    expect(judge.canManageActiveCompetition).toBe(true);
  });
});
