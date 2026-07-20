"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { AnnouncementBanner } from "@/components/announcements/announcement-banner";
import { Lockup } from "@/components/brand/flagpost-mark";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { useCompetitions } from "@/lib/hooks/use-competitions";
import { useLogout } from "@/lib/hooks/use-users";
import { cn } from "@/lib/utils";
import { NOTIFICATIONS } from "@/lib/placeholder-data";
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
const shieldIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2 4 6v6c0 5 3.4 8.7 8 10 4.6-1.3 8-5 8-10V6z" /></svg>
);
const lobbyIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9.5 12 3l9 6.5" /><path d="M5 9v11h14V9" /><path d="M9 20v-6h6v6" /></svg>
);
const settingsIcon: Icon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" /></svg>
);

const COMP_NAV: { href: string; label: string; icon: Icon }[] = [
  { href: "/", label: "Dashboard", icon: dashIcon },
  { href: "/challenges", label: "Challenges", icon: <span className="text-base leading-none">⚑</span> },
  { href: "/scoreboard", label: "Scoreboard", icon: scoreboardIcon },
  { href: "/participants", label: "Participants", icon: peopleIcon },
  { href: "/support", label: "Support", icon: supportIcon },
  { href: "/analytics", label: "Analytics", icon: analyticsIcon },
  { href: "/automations", label: "Automations", icon: boltIcon },
  { href: "/settings", label: "Settings", icon: settingsIcon },
];

const ADMIN_SUBNAV: { href: string; label: string }[] = [
  { href: "/admin/dashboard", label: "Dashboard" },
  { href: "/admin/competitions", label: "Competitions" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/roles", label: "Roles" },
  { href: "/admin/automations", label: "Automations" },
  { href: "/admin/appearance", label: "Appearance" },
  { href: "/admin/settings", label: "Site settings" },
  { href: "/admin/plugins", label: "Plugins" },
];

function useActivePath() {
  const pathname = usePathname();
  return (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isActive = useActivePath();
  const [collapsed, setCollapsed] = React.useState(false);
  const [adminOpen, setAdminOpen] = React.useState(pathname.startsWith("/admin"));
  const logout = useLogout();
  const user = useAuthStore((s) => s.user);

  const initials = React.useMemo(() => {
    const n = user?.display_name?.trim() ?? "";
    if (!n) return "?";
    const parts = n.split(/\s+/);
    return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
  }, [user]);

  const isAdminSection = pathname.startsWith("/admin");
  const navExpanded = !collapsed;

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
    <div className="flex h-screen overflow-hidden">
      <aside
        className={cn(
          "flex flex-shrink-0 flex-col overflow-y-auto border-r border-border bg-card p-3 transition-[width]",
          collapsed ? "w-[56px]" : "w-[248px]",
        )}
      >
        <div className={cn("flex items-center gap-2 px-1 pb-5", collapsed ? "justify-center" : "justify-start")}>
          {navExpanded && <Lockup size={26} theme="dark" />}
          <button
            onClick={() => setCollapsed((c) => !c)}
            title="Toggle sidebar"
            className={cn(
              "rounded-md px-2.5 py-1 text-xl leading-none text-muted-foreground hover:bg-accent/60",
              collapsed ? "" : "ml-auto",
            )}
          >
            {collapsed ? "»" : "«"}
          </button>
        </div>

        <nav className="flex flex-1 flex-col gap-1">
          {COMP_NAV.map((item) => (
            <Link key={item.href} href={item.href} title={item.label} className={navItem(isActive(item.href))}>
              <span className="flex h-4 w-4 items-center justify-center">{item.icon}</span>
              {navExpanded && <span>{item.label}</span>}
            </Link>
          ))}

          <div className="my-2 border-t border-border" />

          <button
            onClick={() => {
              if (collapsed) setCollapsed(false);
              setAdminOpen((o) => !o);
            }}
            title="Admin"
            className={navItem(isAdminSection)}
          >
            <span className="flex h-4 w-4 items-center justify-center">{shieldIcon}</span>
            {navExpanded && (
              <>
                <span className="flex-1 text-left">Admin</span>
                <span className="text-[11px] text-muted-foreground">{adminOpen ? "▾" : "▸"}</span>
              </>
            )}
          </button>
          {navExpanded &&
            adminOpen &&
            ADMIN_SUBNAV.map((item) => (
              <Link key={item.href} href={item.href} className={subNavItem(isActive(item.href))}>
                {item.label}
              </Link>
            ))}
        </nav>

        <div className="grid gap-3 border-t border-border pt-3.5">
          <div className="flex items-center gap-2">
            <Link href="/profile" title="Profile & notification settings" className="flex min-w-0 flex-1 items-center gap-2">
              <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-secondary text-[13px] font-semibold text-secondary-foreground">
                {initials}
              </span>
              {navExpanded && (
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium leading-tight">
                    {user?.display_name ?? "—"}
                  </span>
                  <span className="block text-[11px] leading-tight text-muted-foreground">
                    {user?.email ?? ""}
                  </span>
                </span>
              )}
            </Link>
            {navExpanded && (
              <Button variant="ghost" size="sm" onClick={() => logout.mutate()} disabled={logout.isPending}>
                Sign out
              </Button>
            )}
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar isAdminSection={isAdminSection} pathname={pathname} />
        {/* Live announcement banner on competition-scoped pages (not Admin,
            which is global, nor the lobby, which has no active competition). */}
        {!isAdminSection && pathname !== "/lobby" && <AnnouncementBanner />}
        <main className="flex-1 overflow-y-auto p-8">
          <div className="mx-auto grid max-w-5xl gap-6">{children}</div>
        </main>
      </div>
    </div>
  );
}

function Topbar({ isAdminSection, pathname }: { isAdminSection: boolean; pathname: string }) {
  const palette = useAuthStore((s) => s.palette);
  const togglePalette = useAuthStore((s) => s.togglePalette);
  const activeCompetitionId = useAuthStore((s) => s.activeCompetitionId);
  const setActiveCompetition = useAuthStore((s) => s.setActiveCompetition);
  const { data: competitions } = useCompetitions();

  const [notifOpen, setNotifOpen] = React.useState(false);
  const notifRef = React.useRef<HTMLDivElement>(null);
  const hasUnread = NOTIFICATIONS.some((n) => n.unread);

  // Keep <html data-palette> in sync with the store so the whole surface
  // recolours when the toggle flips (§9 live palette switching).
  React.useEffect(() => {
    document.documentElement.dataset.palette = palette;
  }, [palette]);

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
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [notifOpen]);

  const showSwitcher = !isAdminSection && pathname !== "/profile" && pathname !== "/lobby";

  return (
    <div className="flex flex-shrink-0 items-center gap-4 border-b border-border bg-background px-8 py-3.5">
      {showSwitcher && competitions && competitions.length > 0 && (
        <Select
          value={activeCompetitionId ?? ""}
          onChange={(e) => setActiveCompetition(e.target.value)}
          className="h-9 w-60"
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
          Admin is global — not scoped to a competition
        </span>
      )}
      <div className="flex-1" />

      <div className="relative" ref={notifRef}>
        <button
          onClick={() => setNotifOpen((o) => !o)}
          title="Notifications"
          className="relative flex items-center text-muted-foreground hover:text-foreground"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 22a2.2 2.2 0 0 0 2.2-2.2h-4.4A2.2 2.2 0 0 0 12 22Zm7-6.2V11a7 7 0 0 0-5.5-6.84V3a1.5 1.5 0 0 0-3 0v1.16A7 7 0 0 0 5 11v4.8L3 17.8V19h18v-1.2Z" /></svg>
          {hasUnread && (
            <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-primary" />
          )}
        </button>
        {notifOpen && (
          <div className="absolute right-0 top-[calc(100%+10px)] z-50 w-[400px] overflow-hidden rounded-lg border border-border bg-card shadow-lg">
            <div className="flex items-center justify-between border-b border-border px-4 py-3.5">
              <span className="text-sm font-semibold">Notifications</span>
              <span className="text-xs text-muted-foreground">Placeholder — not wired</span>
            </div>
            <ul className="max-h-80 overflow-y-auto">
              {NOTIFICATIONS.map((n) => (
                <li
                  key={n.id}
                  className={cn("border-b border-border px-4 py-3", n.unread && "bg-primary/5")}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-[13px] font-medium">{n.from}</span>
                    <span className="whitespace-nowrap text-[11px] text-muted-foreground">{n.time}</span>
                  </div>
                  <div className="mt-0.5 text-[13px]">{n.text}</div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <button
        onClick={togglePalette}
        title="Toggle light / dark"
        className="flex items-center text-muted-foreground hover:text-foreground"
      >
        {palette === "dark" ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M21.5 14.5A9 9 0 1 1 9.5 2.5a7 7 0 0 0 12 12Z" /></svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="5" /><g stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="12" y1="1" x2="12" y2="4" /><line x1="12" y1="20" x2="12" y2="23" /><line x1="1" y1="12" x2="4" y2="12" /><line x1="20" y1="12" x2="23" y2="12" /><line x1="4.2" y1="4.2" x2="6.3" y2="6.3" /><line x1="17.7" y1="17.7" x2="19.8" y2="19.8" /><line x1="4.2" y1="19.8" x2="6.3" y2="17.7" /><line x1="17.7" y1="6.3" x2="19.8" y2="4.2" /></g></svg>
        )}
      </button>
    </div>
  );
}
