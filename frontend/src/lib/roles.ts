// Pure helpers for the roles editor (ARCHITECTURE.md §7.4). Kept out of the
// component so the grouping/scoping logic is unit-testable.

import type { PermissionEntry, RoleScope } from "@/lib/types";

export interface CatalogGroup {
  category: string;
  entries: PermissionEntry[];
}

/** Group the permission catalog by category (first-seen order = §7.1 order).
 *  For a competition-scoped role, global permissions are hidden — they'd be
 *  inert (a global permission only grants via a site-wide assignment), so
 *  offering them in a competition role's matrix would just mislead. */
export function groupCatalog(
  catalog: PermissionEntry[],
  scope?: RoleScope,
): CatalogGroup[] {
  const filtered =
    scope === "competition"
      ? catalog.filter((p) => p.scope === "competition")
      : catalog;
  const order: string[] = [];
  const byCategory = new Map<string, PermissionEntry[]>();
  for (const entry of filtered) {
    if (!byCategory.has(entry.category)) {
      byCategory.set(entry.category, []);
      order.push(entry.category);
    }
    byCategory.get(entry.category)!.push(entry);
  }
  return order.map((category) => ({ category, entries: byCategory.get(category)! }));
}
