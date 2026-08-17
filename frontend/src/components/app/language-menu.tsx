"use client";

// Language picker in the topbar (ADR-0029), styled as an icon menu beside the
// notifications and theme controls — a globe glyph that drops a list of the
// shipped locales by endonym. Selection writes the locale cookie and refreshes
// the server render, the same mechanism as the auth/public LocaleSwitcher.
//
// Renders nothing while only one locale ships. The single-locale guard lives in
// a hookless wrapper on purpose (mirroring LocaleSwitcher): an inert mount must
// not require a router/intl context.

import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";

import { setStoredLocale } from "@/i18n/client";
import { LOCALE_LABELS, LOCALES, type Locale } from "@/i18n/config";

export function LanguageMenu() {
  if (LOCALES.length < 2) return null;
  return <LanguageMenuButton />;
}

/** Exported for tests — unreachable via `LanguageMenu` until a second locale
 *  ships, so its hooks never first run in a single-locale production build. */
export function LanguageMenuButton() {
  const t = useTranslations("common");
  const router = useRouter();
  const active = useLocale();
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

  function choose(locale: Locale) {
    setStoredLocale(locale);
    setOpen(false);
    router.refresh();
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        title={t("language")}
        aria-label={t("language")}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center text-muted-foreground hover:text-foreground"
      >
        {/* Globe glyph — the conventional language affordance. */}
        <svg
          aria-hidden="true"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="10" />
          <path d="M2 12h20" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10Z" />
        </svg>
      </button>

      {open && (
        <div className="anim-drop absolute right-0 top-8 z-50 w-44 overflow-hidden rounded-lg border border-border bg-popover shadow-lg">
          <div className="border-b border-border px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {t("language")}
          </div>
          <ul className="py-1">
            {LOCALES.map((l) => (
              <li key={l}>
                <button
                  onClick={() => choose(l)}
                  className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-sm hover:bg-accent/60"
                >
                  <span className="flex-1">{LOCALE_LABELS[l]}</span>
                  {l === active && (
                    <svg
                      width="15"
                      height="15"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className="text-primary"
                    >
                      <path d="M20 6 9 17l-5-5" />
                    </svg>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
