"use client";

// Per-user palette picker in the topbar (§9). Sets a personal palette override
// that wins over the admin's site-wide default; "Use site default" clears it.
// Accent stays site-wide (not per-user), so it isn't offered here.

import * as React from "react";

import { FALLBACK_SETTINGS, useSiteSettings } from "@/lib/hooks/use-site-settings";
import { PALETTES } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

export function PaletteMenu() {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);

  const { data } = useSiteSettings();
  const siteDefault = (data ?? FALLBACK_SETTINGS).default_palette;
  const override = useAuthStore((s) => s.paletteOverride);
  const setOverride = useAuthStore((s) => s.setPaletteOverride);

  const effective = override ?? siteDefault;

  React.useEffect(() => {
    function onDown(e: MouseEvent) {
      if (open && ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const groups: { label: string; mode: "dark" | "light" }[] = [
    { label: "Dark", mode: "dark" },
    { label: "Light", mode: "light" },
  ];

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        title="Theme"
        className="flex items-center text-muted-foreground hover:text-foreground"
      >
        {/* Contrast glyph — the conventional theme/appearance affordance (§9). */}
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 3a9 9 0 0 0 0 18Z" fill="currentColor" stroke="none" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-8 z-50 w-60 overflow-hidden rounded-lg border border-border bg-popover shadow-lg">
          <div className="border-b border-border px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Theme
          </div>
          <ul className="max-h-80 overflow-y-auto py-1">
            <PaletteRow
              label="Use site default"
              swatch={PALETTES.find((p) => p.id === siteDefault)?.swatch}
              active={override === null}
              muted
              onSelect={() => {
                setOverride(null);
                setOpen(false);
              }}
            />
            {groups.map((g) => (
              <React.Fragment key={g.mode}>
                <li className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/70">
                  {g.label}
                </li>
                {PALETTES.filter((p) => p.mode === g.mode).map((p) => (
                  <PaletteRow
                    key={p.id}
                    label={p.label}
                    swatch={p.swatch}
                    active={override !== null && effective === p.id}
                    onSelect={() => {
                      setOverride(p.id);
                      setOpen(false);
                    }}
                  />
                ))}
              </React.Fragment>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function PaletteRow({
  label,
  swatch,
  active,
  muted,
  onSelect,
}: {
  label: string;
  swatch?: { bg: string; card: string; border: string; text: string };
  active: boolean;
  muted?: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        onClick={onSelect}
        className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-sm hover:bg-accent/60"
      >
        <span
          className="h-5 w-5 flex-shrink-0 rounded-full border"
          style={swatch ? { backgroundColor: swatch.bg, borderColor: swatch.border } : undefined}
        />
        <span className={cn("flex-1", muted && "text-muted-foreground")}>{label}</span>
        {active && (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-primary">
            <path d="M20 6 9 17l-5-5" />
          </svg>
        )}
      </button>
    </li>
  );
}
