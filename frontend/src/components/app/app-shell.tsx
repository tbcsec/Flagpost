"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { AiAssistantMount } from "@/components/ai/ai-assistant";
import { AnnouncementBanner } from "@/components/announcements/announcement-banner";
import { DemoBanner } from "@/components/app/demo-banner";
import { CertificateReleaseWatcher } from "@/components/certificates/certificate-release-watcher";
import { UpdateNotice } from "@/components/admin/update-notice";
import { HelpMenu } from "@/components/app/help-menu";
import { UserAvatar } from "@/components/ui/user-avatar";
import { LanguageMenu } from "@/components/app/language-menu";
import { PageIcon } from "@/components/app/page-icons";
import { PoweredByFooter } from "@/components/app/powered-by-footer";
import { Lockup } from "@/components/brand/flagpost-mark";
import { PaletteMenu } from "@/components/theme/palette-menu";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { useCompetitions } from "@/lib/hooks/use-competitions";
import { severityStyle } from "@/lib/announcement-severity";
import { useActivityLive } from "@/lib/hooks/use-activity";
import { useEnabledModules } from "@/lib/hooks/use-modules";
import { usePageNav } from "@/lib/hooks/use-pages";
import { useAccess } from "@/lib/hooks/use-permissions";
import { FALLBACK_SETTINGS, useSiteSettings } from "@/lib/hooks/use-site-settings";
import { useLogout } from "@/lib/hooks/use-users";
import { cn } from "@/lib/utils";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotificationPreferences,
  useNotifications,
} from "@/lib/hooks/use-notifications";
import { useAuthStore } from "@/stores/auth";

// Icons are the plain inline SVGs from the design mock — Flagpost ships no icon
// library (design-system readme → Iconography), so glyphs live at their call
// sites rather than as a dependency.
type Icon = React.ReactNode;

const dashIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></svg>
);
const scoreboardIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 21V13M12 21V7M16 21v-6M2 21h20" /><path d="m4 9 5-5 4 3 6-6" /></svg>
);
const peopleIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2" /><circle cx="10" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>
);
const supportIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" /></svg>
);
const analyticsIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18h18" /><path d="m19 9-5 5-4-4-3 3" /></svg>
);
const boltIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" /></svg>
);
const feedbackIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 3h6a2 2 0 0 1 2 2v0h1a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h1a2 2 0 0 1 2-2z" /><path d="M9 12l2 2 4-4" /></svg>
);
const shieldIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2 4 6v6c0 5 3.4 8.7 8 10 4.6-1.3 8-5 8-10V6z" /></svg>
);
const lobbyIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9.5 12 3l9 6.5" /><path d="M5 9v11h14V9" /><path d="M9 20v-6h6v6" /></svg>
);
const settingsIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" /></svg>
);

const transcriptIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /><path d="M8 8h8M8 12h5" /></svg>
);

// `manage: true` items are shown only to a Judge/organiser of the active
// competition (gated by useAccess); the rest are competitor-facing. `module`
// ties an item to an optional module (§11.3) — the item is hidden when that
// module is disabled for the active competition (nothing there would work).
// `permission` gates an item on one specific grant (for surfaces narrower than
// the manage bundle, e.g. a transcripts-only reviewer role).
// Labels are resolved through `t("nav.<key>")` at render (the arrays are
// module-level, so they can't call the hook themselves) — the key is a typed
// union so a stale key is a compile error, not a raw key path on screen.
type NavKey =
  | "dashboard"
  | "challenges"
  | "scoreboard"
  | "participants"
  | "support"
  | "feedback"
  | "analytics"
  | "automations"
  | "aiTranscripts"
  | "settings";

const COMP_NAV: {
  href: string;
  key: NavKey;
  icon: Icon;
  manage?: boolean;
  module?: string;
  permission?: string;
}[] = [
  { href: "/", key: "dashboard", icon: dashIcon },
  { href: "/challenges", key: "challenges", icon: <span className="text-base leading-none">⚑</span> },
  { href: "/scoreboard", key: "scoreboard", icon: scoreboardIcon },
  { href: "/participants", key: "participants", icon: peopleIcon },
  { href: "/support", key: "support", icon: supportIcon },
  { href: "/feedback", key: "feedback", icon: feedbackIcon, module: "feedback" },
  { href: "/analytics", key: "analytics", icon: analyticsIcon, manage: true, module: "analytics" },
  { href: "/automations", key: "automations", icon: boltIcon, manage: true, module: "automations" },
  // Competitor-assistant transcript review (#98) — its own grant, not the
  // manage bundle, so a transcripts-only reviewer role reaches it.
  { href: "/ai-transcripts", key: "aiTranscripts", icon: transcriptIcon, module: "ai", permission: "ai_view_transcripts" },
  { href: "/settings", key: "settings", icon: settingsIcon, manage: true },
];

type AdminNavKey =
  | "dashboard"
  | "competitions"
  | "users"
  | "roles"
  | "events"
  | "automations"
  | "pages"
  | "siteSettings";

const ADMIN_SUBNAV: { href: string; key: AdminNavKey }[] = [
  { href: "/admin/dashboard", key: "dashboard" },
  { href: "/admin/competitions", key: "competitions" },
  { href: "/admin/users", key: "users" },
  { href: "/admin/roles", key: "roles" },
  { href: "/admin/events", key: "events" },
  { href: "/admin/automations", key: "automations" },
  // Custom pages (#198) get their own route rather than a Site-settings tab:
  // `manage_pages` is a separate, delegable grant, and this is a content
  // manager with an editor rather than a settings form.
  { href: "/admin/pages", key: "pages" },
  // Appearance (#104) and Auth providers (#58) are tabs under Site settings,
  // not their own pages.
  { href: "/admin/settings", key: "siteSettings" },
];

function useActivePath() {
  const pathname = usePathname();
  return (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isActive = useActivePath();
  const t = useTranslations("app");
  // Custom pages in the sidebar (#198). Failure is silent by design: an
  // error or a still-loading query yields no entries, so the shell renders
  // exactly as it did before the feature existed rather than breaking the
  // whole nav over optional content.
  const customPages = usePageNav().data ?? [];
  const [collapsed, setCollapsed] = React.useState(false);
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [adminOpen, setAdminOpen] = React.useState(pathname.startsWith("/admin"));
  const logout = useLogout();
  const user = useAuthStore((s) => s.user);
  const activeCompetitionId = useAuthStore((s) => s.activeCompetitionId);
  const access = useAccess();
  const { data: siteSettings } = useSiteSettings();
  const brand = siteSettings ?? FALLBACK_SETTINGS;
  const platformName = brand.platform_name;
  // The active competition's name, for the assistant's context chip. Shares the
  // Topbar's cached query, so this adds no request.
  const { data: allCompetitions } = useCompetitions();
  const activeCompetition = (allCompetitions ?? []).find(
    (c) => c.id === activeCompetitionId,
  );

  // The theme (palette + accent) is applied globally by <ThemeApplier>, which
  // also restores the saved per-user palette override — the shell no longer
  // touches <html data-palette> itself.

  // Close the mobile drawer whenever the route changes — adjust-during-render
  // (compare against the last seen pathname) instead of a set-state effect.
  const [drawerPath, setDrawerPath] = React.useState(pathname);
  if (drawerPath !== pathname) {
    setDrawerPath(pathname);
    if (mobileOpen) setMobileOpen(false);
  }

  // Escape closes the mobile drawer (keyboard users can't reach the backdrop).
  React.useEffect(() => {
    if (!mobileOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMobileOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [mobileOpen]);

  const initials = React.useMemo(() => {
    const n = user?.display_name?.trim() ?? "";
    if (!n) return "?";
    const parts = n.split(/\s+/);
    return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
  }, [user]);

  const isAdminSection = pathname.startsWith("/admin");
  // Labels show on the desktop drawer unless collapsed, and always in the open
  // mobile drawer (which never collapses to an icon rail).
  const navExpanded = mobileOpen || !collapsed;

  // Role-aware nav: hide manager-only items from competitors, the Admin section
  // from non-admins, and swap the whole competition nav for a Lobby link when a
  // signed-in user has no competition access yet.
  const showLobby = access.ready && access.inLobby;
  // Optional modules disabled for the active competition drop out of the nav
  // (§11.3). Member-readable, so it gates competitors' nav too. Until it loads
  // we don't filter — modules are on by default, so hiding-then-showing would
  // flicker more than the rare disabled case.
  const enabledModules = useEnabledModules(
    activeCompetitionId ?? "",
    Boolean(activeCompetitionId) && access.ready && !access.inLobby,
  );
  // The competition's activity room (#18): one shell-level socket that turns
  // backend event pings into query refreshes, so every page under the shell is
  // live. Gated like the modules query — a lobby user has no room access.
  useActivityLive(access.ready && !access.inLobby ? activeCompetitionId : null);
  const compNav = COMP_NAV.filter((item) => {
    if (item.manage && !access.canManageActiveCompetition) return false;
    if (item.permission && !access.has(item.permission)) return false;
    if (item.module && enabledModules.data && !enabledModules.data.includes(item.module))
      return false;
    return true;
  });
  const adminDenied = isAdminSection && access.ready && !access.isAdmin;

  // A lobby user (no competition access) has no competition-scoped pages to be
  // on — send them to the lobby (they can still reach their profile).
  React.useEffect(() => {
    if (showLobby && pathname !== "/lobby" && pathname !== "/profile") {
      router.replace("/lobby");
    }
  }, [showLobby, pathname, router]);

  const navItem = (active: boolean) =>
    cn(
      "flex items-center gap-3 rounded-md text-sm transition-colors cursor-pointer",
      collapsed ? "justify-center py-2.5" : "px-3 py-2.5",
      active
        ? "bg-accent font-semibold text-foreground"
        : "font-medium text-muted-foreground hover:bg-accent/60",
    );

  const subNavItem = (active: boolean) =>
    cn(
      "rounded-md py-1.5 pl-[34px] pr-3 text-sm transition-colors cursor-pointer",
      active
        ? "bg-accent font-semibold text-foreground"
        : "font-medium text-muted-foreground hover:bg-accent/60",
    );

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* Keyboard users can jump past the nav straight to page content. */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-primary-foreground"
      >
        {t("skipToContent")}
      </a>
      {/* Demo-instance banner spans the full width above the shell. */}
      <DemoBanner />
      {/* "A newer version is available" (#111) — renders nothing unless the
          viewer can act on it and there's genuinely an update. */}
      <UpdateNotice />
      <div className="flex min-h-0 flex-1 overflow-hidden">
      {/* Mobile drawer backdrop. */}
      {mobileOpen && (
        <div
          className="anim-fade fixed inset-0 z-30 bg-black/50 md:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}
      <aside
        className={cn(
          "flex flex-col overflow-y-auto border-r border-border bg-card p-3",
          // Off-canvas drawer on mobile, static rail on md+.
          "fixed inset-y-0 left-0 z-40 w-[248px] transition-transform md:static md:z-auto md:flex-shrink-0 md:translate-x-0 md:transition-[width]",
          mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
          collapsed ? "md:w-[56px]" : "md:w-[248px]",
        )}
      >
        <div className={cn("flex items-center gap-2 px-1 pb-5", collapsed && !mobileOpen ? "md:justify-center" : "justify-start")}>
          {navExpanded && (
            <Lockup
              size={26}
              theme="dark"
              label={platformName}
              logoUrl={brand.logo_url}
              showWordmark={brand.show_wordmark}
            />
          )}
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            title={t("toggleSidebar")}
            aria-label={collapsed ? t("expandSidebar") : t("collapseSidebar")}
            aria-expanded={!collapsed}
            className={cn(
              "ml-auto hidden rounded-md px-2.5 py-1 text-xl leading-none text-muted-foreground hover:bg-accent/60 md:block",
              collapsed && "md:ml-0",
            )}
          >
            <span aria-hidden="true">{collapsed ? "»" : "«"}</span>
          </button>
        </div>

        <nav aria-label={t("mainNav")} className="flex flex-1 flex-col gap-1">
          {showLobby ? (
            <Link href="/lobby" title={t("nav.lobby")} className={navItem(isActive("/lobby"))}>
              <span className="flex h-4 w-4 items-center justify-center">{lobbyIcon}</span>
              {navExpanded && <span>{t("nav.lobby")}</span>}
            </Link>
          ) : (
            compNav.map((item) => {
              const label = t(`nav.${item.key}`);
              return (
                <Link key={item.href} href={item.href} title={label} className={navItem(isActive(item.href))}>
                  <span className="flex h-4 w-4 items-center justify-center">{item.icon}</span>
                  {navExpanded && <span>{label}</span>}
                </Link>
              );
            })
          )}

          {/* Custom pages (#198). Not permission-gated: `manage_pages` governs
              *authoring*, and the API already returns only what this viewer may
              read. Titles are operator-authored data, so they render verbatim
              rather than through t() — unlike every built-in item above, whose
              label comes from the message catalog (ADR-0034). */}
          {customPages.length > 0 && (
            <>
              <div className="my-2 border-t border-border" />
              {customPages.map((page) => {
                const href = `/p/${page.slug}`;
                return (
                  <Link
                    key={page.slug}
                    href={href}
                    title={page.title}
                    className={navItem(isActive(href))}
                  >
                    <span className="flex h-4 w-4 items-center justify-center">
                      <PageIcon name={page.icon} />
                    </span>
                    {navExpanded && <span className="truncate">{page.title}</span>}
                  </Link>
                );
              })}
            </>
          )}

          {access.isAdmin && (
            <>
              <div className="my-2 border-t border-border" />
              <button
                type="button"
                onClick={() => {
                  if (collapsed) setCollapsed(false);
                  setAdminOpen((o) => !o);
                }}
                title={t("nav.admin")}
                aria-expanded={adminOpen}
                className={navItem(isAdminSection)}
              >
                <span className="flex h-4 w-4 items-center justify-center">{shieldIcon}</span>
                {navExpanded && (
                  <>
                    <span className="flex-1 text-left">{t("nav.admin")}</span>
                    <span aria-hidden="true" className="text-[11px] text-muted-foreground">{adminOpen ? "▾" : "▸"}</span>
                  </>
                )}
              </button>
              {navExpanded &&
                adminOpen &&
                ADMIN_SUBNAV.map((item) => (
                  <Link key={item.href} href={item.href} className={subNavItem(isActive(item.href))}>
                    {t(`adminNav.${item.key}`)}
                  </Link>
                ))}
            </>
          )}
        </nav>

        <div className="grid gap-3 border-t border-border pt-3.5">
          {/* min-w-0: as a grid item this row defaults to `min-width: auto`, so
              it would refuse to shrink below its content and push "Sign out"
              out of the rail — the `truncate` below can't engage without it (#48). */}
          <div className="flex min-w-0 items-center gap-2">
            <Link href="/profile" title={t("profileSettings")} className="flex min-w-0 flex-1 items-center gap-2">
              {user ? (
                <UserAvatar
                  userId={user.id}
                  name={user.display_name}
                  avatarUpdatedAt={user.avatar_updated_at}
                  size={32}
                />
              ) : (
                <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-secondary text-[13px] font-semibold text-secondary-foreground">
                  {initials}
                </span>
              )}
              {navExpanded && (
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium leading-tight">
                    {user?.display_name ?? "—"}
                  </span>
                  {/* Truncate like the display name above it: a long email must
                      not push "Sign out" out of the rail (#48). The title gives
                      the full value back on hover. */}
                  <span
                    className="block truncate text-[11px] leading-tight text-muted-foreground"
                    title={user?.email ?? undefined}
                  >
                    {user?.email ?? ""}
                  </span>
                </span>
              )}
            </Link>
            {navExpanded && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => logout.mutate()}
                disabled={logout.isPending}
                // Never give up width to the identity block beside it.
                className="flex-shrink-0"
              >
                {t("signOut")}
              </Button>
            )}
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          isAdminSection={isAdminSection}
          pathname={pathname}
          onOpenMenu={() => setMobileOpen(true)}
        />
        {/* Live announcement banner on competition-scoped pages (not Admin,
            which is global, nor the lobby, which has no active competition). */}
        {!isAdminSection && pathname !== "/lobby" && <AnnouncementBanner />}
        <main id="main-content" className="flex-1 overflow-y-auto p-4 md:p-8">
          {/* A min-height flex column so the footer sits at the bottom on short
              pages (mt-auto) without stretching the content grid's rows. */}
          <div className="mx-auto flex min-h-full max-w-5xl flex-col">
            <div className="grid gap-6">
              {adminDenied ? (
                <div className="rounded-lg border border-border bg-card p-10 text-center">
                  <p className="text-sm text-muted-foreground">
                    {t("adminNoAccess")}
                  </p>
                </div>
              ) : (
                children
              )}
            </div>
            {/* One-time certificate-release celebration, once per release (#219). */}
            <CertificateReleaseWatcher />
            <div className="mt-auto flex flex-col items-center">
              <PoweredByFooter />
            </div>
          </div>
        </main>
      </div>
      </div>
      {/* The organiser assistant launcher (#98). Competition-scoped, so it's
          shown only on a competition page (not the global Admin section, not the
          lobby); <AiAssistantMount> itself checks the viewer is staff and the
          module is enabled before rendering anything. Fixed-positioned, so its
          place at the shell root — an ancestor with no transform — keeps it
          anchored to the viewport. */}
      {access.ready && !access.inLobby && !isAdminSection && activeCompetitionId && (
        <AiAssistantMount
          competitionId={activeCompetitionId}
          competitionName={activeCompetition?.name}
        />
      )}
    </div>
  );
}

function Topbar({
  isAdminSection,
  pathname,
  onOpenMenu,
}: {
  isAdminSection: boolean;
  pathname: string;
  onOpenMenu: () => void;
}) {
  const t = useTranslations("app");
  // Announcement severity chips translate through the announcements namespace.
  const ta = useTranslations("announcements");
  const rel = useRelativeTime();
  const activeCompetitionId = useAuthStore((s) => s.activeCompetitionId);
  const setActiveCompetition = useAuthStore((s) => s.setActiveCompetition);
  const { data: allCompetitions } = useCompetitions();
  // Archived competitions drop out of the switcher (they're closed out) — but
  // keep the current selection visible even if it was just archived.
  const competitions = (allCompetitions ?? []).filter(
    (c) => !c.archived_at || c.id === activeCompetitionId,
  );

  const [notifOpen, setNotifOpen] = React.useState(false);
  const notifRef = React.useRef<HTMLDivElement>(null);
  const { data: notifications } = useNotifications();
  // Keep the delivery-hint cache (sound/browser) warm for the ticket cue + WS
  // handler, which read it outside React.
  useNotificationPreferences();
  const markRead = useMarkNotificationRead();
  const markAllRead = useMarkAllNotificationsRead();
  const items = notifications ?? [];
  const unreadCount = items.reduce((n, item) => (item.read ? n : n + 1), 0);
  const hasUnread = unreadCount > 0;

  // Default the active competition to the first one once the list loads.
  React.useEffect(() => {
    if (!activeCompetitionId && competitions && competitions.length > 0) {
      setActiveCompetition(competitions[0].id);
    }
  }, [activeCompetitionId, competitions, setActiveCompetition]);

  React.useEffect(() => {
    function onDown(e: MouseEvent) {
      if (notifOpen && notifRef.current && !notifRef.current.contains(e.target as Node)) {
        setNotifOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setNotifOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [notifOpen]);

  const showSwitcher = !isAdminSection && pathname !== "/profile" && pathname !== "/lobby";

  return (
    <div className="flex flex-shrink-0 items-center gap-3 border-b border-border bg-background px-4 py-3.5 md:gap-4 md:px-8">
      <button
        onClick={onOpenMenu}
        title={t("openMenu")}
        aria-label={t("openMenu")}
        className="text-muted-foreground hover:text-foreground md:hidden"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></svg>
      </button>
      {showSwitcher && competitions && competitions.length > 0 && (
        <Select
          value={activeCompetitionId ?? ""}
          onChange={(e) => setActiveCompetition(e.target.value)}
          className="h-9 w-44 md:w-60"
        >
          {competitions.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
      )}
      {isAdminSection && (
        <span className="text-xs text-muted-foreground">
          {t("adminGlobalScope")}
        </span>
      )}
      <div className="flex-1" />

      <div className="relative" ref={notifRef}>
        <button
          type="button"
          onClick={() => setNotifOpen((o) => !o)}
          title={t("notifications.title")}
          aria-label={
            hasUnread
              ? t("notifications.unread", { count: unreadCount })
              : t("notifications.title")
          }
          aria-haspopup="menu"
          aria-expanded={notifOpen}
          className="relative flex items-center text-muted-foreground hover:text-foreground"
        >
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 22a2.2 2.2 0 0 0 2.2-2.2h-4.4A2.2 2.2 0 0 0 12 22Zm7-6.2V11a7 7 0 0 0-5.5-6.84V3a1.5 1.5 0 0 0-3 0v1.16A7 7 0 0 0 5 11v4.8L3 17.8V19h18v-1.2Z" /></svg>
          {unreadCount > 0 && (
            // A count, not a bare dot — "3 waiting" reads very differently from
            // "something happened at some point".
            <span
              aria-hidden="true"
              className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold leading-none text-primary-foreground"
            >
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </button>
        {notifOpen && (
          <div className="anim-drop absolute right-0 top-[calc(100%+10px)] z-50 w-[400px] overflow-hidden rounded-lg border border-border bg-card shadow-lg">
            <div className="flex items-center justify-between border-b border-border px-4 py-3.5">
              <span className="text-sm font-semibold">{t("notifications.title")}</span>
              {hasUnread && (
                <button
                  onClick={() => markAllRead.mutate()}
                  className="text-xs text-primary hover:underline"
                >
                  {t("notifications.markAllRead")}
                </button>
              )}
            </div>
            {items.length === 0 ? (
              <div className="px-4 py-8 text-center text-[13px] text-muted-foreground">
                {t("notifications.empty")}
              </div>
            ) : (
              <ul className="max-h-80 overflow-y-auto">
                {items.map((n) => {
                  // An announcement notification carries its urgency in the
                  // type (`announcement.<severity>`), so the row can show the
                  // same accent the banner used.
                  const announced = n.type.startsWith("announcement.")
                    ? severityStyle(n.type.slice("announcement.".length))
                    : null;
                  const body = (
                    <div className="flex gap-2.5">
                      {/* Explicit per-row unread marker — the old faint row
                          tint alone was easy to miss. */}
                      <span
                        aria-hidden="true"
                        className={cn(
                          "mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full",
                          n.read ? "bg-transparent" : "bg-primary",
                        )}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="text-[13px] font-medium">{n.title}</span>
                          <span className="whitespace-nowrap text-[11px] text-muted-foreground">
                            {rel(n.created_at)}
                          </span>
                        </div>
                        {announced && (
                          <span
                            className={cn(
                              "mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                              announced.chip,
                            )}
                          >
                            {ta(`severity.${announced.key}`)}
                          </span>
                        )}
                        {n.body && (
                          <div className="mt-0.5 text-[13px] text-muted-foreground">
                            {n.body}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                  const onActivate = () => {
                    if (!n.read) markRead.mutate(n.id);
                    setNotifOpen(false);
                  };
                  // Only ever follow an internal, same-origin path — never an
                  // absolute/scheme URL. Notification links are server-built
                  // today, but this defends against a future producer letting a
                  // "javascript:"/"//evil.com" value reach an anchor href.
                  const safeLink =
                    n.link && n.link.startsWith("/") && !n.link.startsWith("//")
                      ? n.link
                      : null;
                  return (
                    <li
                      key={n.id}
                      className={cn(
                        "border-b border-border",
                        !n.read && "bg-primary/5",
                      )}
                    >
                      {safeLink ? (
                        <Link href={safeLink} onClick={onActivate} className="block px-4 py-3 hover:bg-muted/50">
                          {body}
                        </Link>
                      ) : (
                        <button onClick={onActivate} className="block w-full px-4 py-3 text-left hover:bg-muted/50">
                          {body}
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </div>

      <HelpMenu />
      <LanguageMenu />
      <PaletteMenu />
    </div>
  );
}
