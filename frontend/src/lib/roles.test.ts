import { describe, expect, it } from "vitest";

import { groupCatalog } from "@/lib/roles";
import type { PermissionEntry } from "@/lib/types";

const catalog: PermissionEntry[] = [
  { key: "challenge_view", category: "Challenges", scope: "competition", reserved: false },
  { key: "challenge_edit", category: "Challenges", scope: "competition", reserved: false },
  { key: "manage_users", category: "Users & Roles", scope: "global", reserved: false },
  { key: "manage_roles", category: "Users & Roles", scope: "global", reserved: false },
];

describe("groupCatalog", () => {
  it("groups by category in first-seen order", () => {
    const groups = groupCatalog(catalog);
    expect(groups.map((g) => g.category)).toEqual(["Challenges", "Users & Roles"]);
    expect(groups[0].entries.map((e) => e.key)).toEqual(["challenge_view", "challenge_edit"]);
  });

  it("hides global permissions for a competition-scoped role", () => {
    const groups = groupCatalog(catalog, "competition");
    expect(groups.map((g) => g.category)).toEqual(["Challenges"]);
    expect(groups.flatMap((g) => g.entries).every((e) => e.scope === "competition")).toBe(true);
  });

  it("keeps global permissions for a global-scoped role", () => {
    const groups = groupCatalog(catalog, "global");
    expect(groups.map((g) => g.category)).toEqual(["Challenges", "Users & Roles"]);
  });
});
