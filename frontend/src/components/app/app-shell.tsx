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
import {
  isCompetitionScopedPath,
  shouldCheckProgrammingProblems,
  shouldRedirectToLobby,
  shouldShowJoinPanel,
  visibleCompNav,
} from "@/components/app/nav-visibility";
import { CompetitionSwitcher } from "@/components/app/competition-switcher";
import { ModuleIcon } from "@/components/app/module-icons";
import { JoinCompetitionPanel } from "@/components/competitions/join-competition-panel";
import { visibleAdminSurfaces } from "@/lib/admin-surfaces";
import { UserAvatar } from "@/components/ui/user-avatar";
import { LanguageMenu } from "@/components/app/language-menu";
import { PageIcon } from "@/components/app/page-icons";
import { PoweredByFooter } from "@/components/app/powered-by-footer";
import { Lockup } from "@/components/brand/flagpost-mark";
import { PaletteMenu } from "@/components/theme/palette-menu";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompetitions } from "@/lib/hooks/use-competitions";
import { severityStyle } from "@/lib/announcement-severity";
import { useActivityLive } from "@/lib/hooks/use-activity";
import { useEnabledModules } from "@/lib/hooks/use-modules";
import { usePageNav } from "@/lib/hooks/use-pages";
import { useHasProgrammingProblems } from "@/lib/hooks/use-judge";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useBrandSettings, useSiteSettings } from "@/lib/hooks/use-site-settings";
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

// Icons are plain inline SVGs — Flagpost ships no icon library (design-system
// readme → Iconography). They live in module-icons.tsx, shared with the module
// tiles in Settings → Modules so a module looks the same in both (#502).
type Icon = React.ReactNode;
const icon = (name: string): Icon => <ModuleIcon name={name} />;

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
  | "instances"
  | "judging"
  | "settings";

const COMP_NAV: {
  href: string;
  key: NavKey;
  icon: Icon;
  manage?: boolean;
  module?: string;
  permission?: string;
}[] = [
  { href: "/", key: "dashboard", icon: icon("dashboard") },
  { href: "/challenges", key: "challenges", icon: <span className="text-base leading-none">⚑</span> },
  { href: "/scoreboard", key: "scoreboard", icon: icon("scoring") },
  { href: "/participants", key: "participants", icon: icon("teams") },
  { href: "/support", key: "support", icon: icon("tickets") },
  { href: "/feedback", key: "feedback", icon: icon("feedback"), module: "feedback" },
  { href: "/analytics", key: "analytics", icon: icon("analytics"), manage: true, module: "analytics" },
  { href: "/automations", key: "automations", icon: icon("automations"), manage: true, module: "automations" },
  // Competitor-assistant transcript review (#98) — its own grant, not the
  // manage bundle, so a transcripts-only reviewer role reaches it.
  { href: "/ai-transcripts", key: "aiTranscripts", icon: icon("ai"), module: "ai", permission: "ai_view_transcripts" },
  // Running-instance ops (#266) — its own grant (instance_view), shown only when
  // the instances module is enabled for the competition.
  { href: "/instances", key: "instances", icon: icon("instances"), module: "instances", permission: "instance_view" },
  // The jury console (#450) — its own grant (judging_view), shown only when the
  // code judge module is on for the competition AND it has a programming
  // problem (see `hasProgrammingProblems` below).
  { href: "/judging", key: "judging", icon: icon("judge"), module: "judge", permission: "judging_view" },
  { href: "/settings", key: "settings", icon: icon("settings"), manage: true },
];

// The Admin sub-nav comes from the shared surface catalogue (lib/admin-surfaces,
// #477): each entry gated on its own global grant, so the section lists exactly
// the pages this viewer can open. Pages (#198) and Marketplace (#389) are their
// own routes rather than Site-settings tabs because their grants are separately
// delegable; Appearance (#104) and Auth providers (#58) are tabs under Site
// settings, not pages.

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
  const brand = useBrandSettings();
  const platformName = brand.platform_name;
  // Hide the admin Skills matrix link when the site-wide skills web is off (#364).
  const skillsEnabled = useSiteSettings().data?.skills_enabled ?? false;
  const adminSubnav = visibleAdminSurfaces(access.hasGlobal).filter(
    (item) => item.key !== "skills" || skillsEnabled,
  );
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
  // The switcher also lists public competitions this user hasn't joined
  // (#478). On one of those, competition pages show a join panel instead of a
  // page the server would refuse, and nothing competition-scoped is fetched.
  const memberOfActive = access.ready && access.memberOfActive;
  const joinFirst = shouldShowJoinPanel({
    ...access,
    hasActiveCompetition: Boolean(activeCompetition),
    pathname,
  });
  // Until permissions and the competition list are in, a competition page
  // can't know whether to render or offer a join — and rendering would send
  // requests the server refuses for a competition you haven't joined.
  const settling =
    Boolean(activeCompetitionId) &&
    isCompetitionScopedPath(pathname) &&
    ((!access.ready && !access.failed) || allCompetitions === undefined);
  // Optional modules disabled for the active competition drop out of the nav
  // (§11.3). Member-readable, so it gates competitors' nav too. Until it loads
  // we don't filter — modules are on by default, so hiding-then-showing would
  // flicker more than the rare disabled case.
  const enabledModules = useEnabledModules(
    activeCompetitionId ?? "",
    Boolean(activeCompetitionId) && memberOfActive,
  );
  // The competition's activity room (#18): one shell-level socket that turns
  // backend event pings into query refreshes, so every page under the shell is
  // live. Gated like the modules query — a non-member has no room access.
  useActivityLive(memberOfActive ? activeCompetitionId : null);
  // Judging shows only once the competition has a programming problem.
  const hasProgrammingProblems = useHasProgrammingProblems(
    activeCompetitionId ?? "",
    shouldCheckProgrammingProblems(access, enabledModules.data),
  );
  const compNav = visibleCompNav(
    COMP_NAV,
    access,
    enabledModules.data,
    hasProgrammingProblems.data,
  );
  const adminDenied = isAdminSection && access.ready && !access.isAdmin;

  // A lobby user (no competition access) has no competition-scoped pages to be
  // on — send them to the lobby (they can still reach their profile, and a
  // narrow global delegate keeps the Admin pages their grant opens, #477).
  const toLobby = shouldRedirectToLobby({ showLobby, pathname, isAdmin: access.isAdmin });
  React.useEffect(() => {
    if (toLobby) router.replace("/lobby");
  }, [toLobby, router]);

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
              <span className="flex h-4 w-4 items-center justify-center">{icon("lobby")}</span>
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
                <span className="flex h-4 w-4 items-center justify-center">{icon("admin")}</span>
                {navExpanded && (
                  <>
                    <span className="flex-1 text-left">{t("nav.admin")}</span>
                    <span aria-hidden="true" className="text-[11px] text-muted-foreground">{adminOpen ? "▾" : "▸"}</span>
                  </>
                )}
              </button>
              {navExpanded &&
                adminOpen &&
                adminSubnav.map((item) => (
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
                // Username only (#301): the email always truncated in the rail
                // and lives on the profile page this block links to. Truncation
                // still matters — a long name must not push "Sign out" out of
                // the rail (#48); the title gives the full value back on hover.
                <span
                  className="min-w-0 flex-1 truncate text-[13px] font-medium leading-tight"
                  title={user?.display_name ?? undefined}
                >
                  {user?.display_name ?? "—"}
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
        {!isAdminSection && pathname !== "/lobby" && memberOfActive && <AnnouncementBanner />}
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
              ) : settling ? (
                <Skeleton className="h-64 w-full" />
              ) : joinFirst && activeCompetition ? (
                <JoinCompetitionPanel competition={activeCompetition} />
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
      {memberOfActive && !isAdminSection && activeCompetitionId && (
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
      <CompetitionSwitcher visible={showSwitcher} />
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
                  // A judges' clarification (#450) rides the same category,
                  // as does word that one was withdrawn.
                  const clarification = n.type === "announcement.clarification";
                  const withdrawnNotice = n.type === "announcement.clarification_withdrawn";
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
                            {withdrawnNotice
                              ? ta("clarificationWithdrawn")
                              : clarification
                                ? ta("clarification")
                                : ta(`severity.${announced.key}`)}
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
