// The Admin section's surfaces and the global grant(s) that unlock each (#477).
//
// The section is global scope, so only *global* grants count — a judge's
// competition-scoped automation_view must not open Admin → Automations. Pure
// and shared: the shell derives "can open the Admin section at all" and the
// visible sub-nav from this list, and /admin lands on the first page the
// viewer can use, so a narrow global delegate (event log only, say) reaches
// their page instead of "You don't have access to the admin area". Each page
// still enforces its own grant, and the API is the real gate — this only
// decides what to show.

export type AdminNavKey =
  | "dashboard"
  | "skills"
  | "competitions"
  | "users"
  | "roles"
  | "events"
  | "automations"
  | "pages"
  | "marketplace"
  | "siteSettings";

export interface AdminSurface {
  key: AdminNavKey;
  href: string;
  /** Any one of these global grants unlocks the surface. */
  grants: readonly string[];
}

/** In sub-nav order. A grant that opens no page opens no section: the list
 *  names what each page needs to *render*, not every grant it can use. */
export const ADMIN_SURFACES: readonly AdminSurface[] = [
  { key: "dashboard", href: "/admin/dashboard", grants: ["view_global_analytics"] },
  // Same grant as the dashboard; the shell also hides it while the site-wide
  // skills web is off (#364). Never first, so /admin never lands on it alone.
  { key: "skills", href: "/admin/skills", grants: ["view_global_analytics"] },
  // Each row action has its own grant (create/clone, archive, delete); any one
  // opens the list, and the page shows only the actions the viewer holds.
  {
    key: "competitions",
    href: "/admin/competitions",
    grants: ["create_competition", "edit_competition", "delete_competition"],
  },
  // The directory needs view_all_users; token oversight (manage_api_tokens)
  // lives on the same page and opens it alone, showing just the token panel.
  // manage_users only adds actions to the directory, so it opens nothing.
  { key: "users", href: "/admin/users", grants: ["view_all_users", "manage_api_tokens"] },
  { key: "roles", href: "/admin/roles", grants: ["manage_roles"] },
  { key: "events", href: "/admin/events", grants: ["view_audit_log"] },
  // Global rules: listing them needs a *global* automation_view.
  { key: "automations", href: "/admin/automations", grants: ["automation_view"] },
  { key: "pages", href: "/admin/pages", grants: ["manage_pages"] },
  {
    key: "marketplace",
    href: "/admin/marketplace",
    grants: ["install_content_pack", "manage_marketplace"],
  },
  // The general tabs share one grant; Auth, AI, Instances and Code judge are
  // higher-stakes tabs with their own, and the page opens for any of them.
  {
    key: "siteSettings",
    href: "/admin/settings",
    grants: [
      "manage_site_settings",
      "manage_auth_providers",
      "manage_ai",
      "manage_instance_infra",
      "manage_judge_infra",
    ],
  },
];

/** The global-scope permissions — mirrors `scope="global"` in
 *  backend/auth/permissions.py; keep the two in step. Everything else is
 *  competition-scope, so holding one of *those* globally (a custom global role
 *  can) reaches into every competition, while these only reach the Admin
 *  section. The lobby rule turns on that difference. */
export const GLOBAL_SCOPE_PERMISSIONS: ReadonlySet<string> = new Set([
  "create_competition",
  "install_content_pack",
  "manage_ai",
  "manage_api_tokens",
  "manage_auth_providers",
  "manage_instance_infra",
  "manage_judge_infra",
  "manage_marketplace",
  "manage_pages",
  "manage_roles",
  "manage_site_settings",
  "manage_users",
  "view_all_users",
  "view_audit_log",
  "view_global_analytics",
]);

type HasGlobal = (permission: string) => boolean;

/** The sub-nav entries this viewer can open, in order. */
export function visibleAdminSurfaces(hasGlobal: HasGlobal): AdminSurface[] {
  return ADMIN_SURFACES.filter((surface) => surface.grants.some(hasGlobal));
}

/** Whether the Admin section exists for this viewer at all. */
export function hasAdminAccess(hasGlobal: HasGlobal): boolean {
  return ADMIN_SURFACES.some((surface) => surface.grants.some(hasGlobal));
}

/** Where /admin should land: the first page the viewer can open, or null. */
export function firstAdminHref(hasGlobal: HasGlobal): string | null {
  return visibleAdminSurfaces(hasGlobal)[0]?.href ?? null;
}
