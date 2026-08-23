"use client";

// Topbar help menu: the bundled user-guide PDFs, role-aware — everyone gets
// the Competitor guide; competition staff add the Judge guide; admins add the
// Admin guide. Same self-contained dropdown pattern as PaletteMenu.

import { useTranslations } from "next-intl";
import * as React from "react";

import { GUIDE_PDFS } from "@/lib/guides";
import { useAccess } from "@/lib/hooks/use-permissions";

export function HelpMenu() {
  const t = useTranslations("app.help");
  const access = useAccess();
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    function onDown(e: MouseEvent) {
      if (open && ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const guides = [
    { href: GUIDE_PDFS.competitor, label: t("competitor"), show: true },
    { href: GUIDE_PDFS.judge, label: t("judge"), show: access.canManageActiveCompetition },
    { href: GUIDE_PDFS.admin, label: t("admin"), show: access.isAdmin },
  ].filter((g) => g.show);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        title={t("title")}
        aria-label={t("title")}
        className="flex items-center text-muted-foreground hover:text-foreground"
      >
        {/* Circled question mark — the conventional help affordance. */}
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      </button>

      {open && (
        <div className="anim-drop absolute right-0 top-8 z-50 w-60 overflow-hidden rounded-lg border border-border bg-popover shadow-lg">
          <div className="border-b border-border px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {t("title")}
          </div>
          <ul className="py-1">
            {guides.map((g) => (
              <li key={g.href}>
                {/* Static PDFs bundled with this install — open in a new tab. */}
                <a
                  href={g.href}
                  target="_blank"
                  rel="noreferrer"
                  onClick={() => setOpen(false)}
                  className="flex w-full items-center gap-2.5 px-3 py-2 text-sm hover:bg-accent/60"
                >
                  <GuideIcon />
                  <span className="flex-1">{g.label}</span>
                  <span className="text-[10px] font-semibold uppercase text-muted-foreground">
                    PDF
                  </span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function GuideIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-muted-foreground" aria-hidden>
      <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
    </svg>
  );
}
