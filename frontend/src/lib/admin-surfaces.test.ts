import { describe, expect, it } from "vitest";

import {
  ADMIN_SURFACES,
  firstAdminHref,
  hasAdminAccess,
  visibleAdminSurfaces,
} from "@/lib/admin-surfaces";

// The Admin section used to exist only for manage_users / manage_roles /
// create_competition, so a global delegate holding a narrower grant (event log,
// auth providers, backups…) could never reach the page it unlocked (#477).

const holding = (...grants: string[]) => (p: string) => grants.includes(p);
const keys = (hasGlobal: (p: string) => boolean) =>
  visibleAdminSurfaces(hasGlobal).map((s) => s.key);

const ADMINISTRATOR = [
  "view_global_analytics", "create_competition", "view_all_users", "manage_users",
  "manage_roles", "view_audit_log", "automation_view", "manage_pages",
  "install_content_pack", "manage_marketplace", "manage_site_settings",
];

describe("the Admin section's surfaces", () => {
  it("opens every page for an administrator, in sub-nav order", () => {
    const admin = holding(...ADMINISTRATOR);
    expect(keys(admin)).toEqual(ADMIN_SURFACES.map((s) => s.key));
    expect(hasAdminAccess(admin)).toBe(true);
    expect(firstAdminHref(admin)).toBe("/admin/dashboard");
  });

  it("opens exactly the delegate's page for a narrow global grant", () => {
    const auditor = holding("view_audit_log");
    expect(keys(auditor)).toEqual(["events"]);
    expect(hasAdminAccess(auditor)).toBe(true);
    expect(firstAdminHref(auditor)).toBe("/admin/events");

    expect(keys(holding("manage_auth_providers"))).toEqual(["siteSettings"]);
    expect(keys(holding("manage_marketplace"))).toEqual(["marketplace"]);
    expect(keys(holding("manage_pages"))).toEqual(["pages"]);
  });

  it("still opens the section for each of the original three grants", () => {
    expect(keys(holding("create_competition"))).toEqual(["competitions"]);
    expect(keys(holding("manage_roles"))).toEqual(["roles"]);
    // manage_users adds actions to the directory, which view_all_users opens.
    expect(keys(holding("manage_users", "view_all_users"))).toEqual(["users"]);
  });

  it("shows nothing for a viewer with no global grant that opens a page", () => {
    // A judge's competition-scoped grants are not global — the caller passes
    // a global-only predicate, so these all read as absent.
    const none = holding();
    expect(keys(none)).toEqual([]);
    expect(hasAdminAccess(none)).toBe(false);
    expect(firstAdminHref(none)).toBeNull();
    // A grant that opens no page (manage_users only adds actions to a
    // directory that needs view_all_users) doesn't conjure an empty section.
    expect(hasAdminAccess(holding("manage_users"))).toBe(false);
  });

  it("opens Users for token oversight alone", () => {
    // The token panel lives on the Users page and has its own grant.
    expect(keys(holding("manage_api_tokens"))).toEqual(["users"]);
  });

  it("opens Competitions for any of its row actions' grants", () => {
    expect(keys(holding("edit_competition"))).toEqual(["competitions"]);
    expect(keys(holding("delete_competition"))).toEqual(["competitions"]);
  });

  it("never lands /admin on Skills alone", () => {
    // Skills shares the dashboard's grant and follows it, so the first visible
    // page for a view_global_analytics holder is always the dashboard.
    expect(firstAdminHref(holding("view_global_analytics"))).toBe("/admin/dashboard");
  });
});
