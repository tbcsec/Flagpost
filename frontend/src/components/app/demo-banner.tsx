"use client";

import { FALLBACK_SETTINGS, useSiteSettings } from "@/lib/hooks/use-site-settings";

// A full-width bar shown on every page of a demo instance (config.demo_mode),
// making it obvious the data is throwaway. The hourly reset is done externally;
// this just states it. Non-dismissible on purpose.
export function DemoBanner() {
  const { data } = useSiteSettings();
  if (!(data ?? FALLBACK_SETTINGS).demo_mode) return null;
  return (
    <div className="flex flex-shrink-0 items-center justify-center gap-2 border-b border-warning/40 bg-warning/15 px-4 py-1.5 text-center text-[13px] font-medium text-foreground">
      <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-warning" aria-hidden="true" />
      <span>
        Demo instance — data is public and{" "}
        <strong className="font-semibold">resets every hour, on the hour</strong>.
      </span>
    </div>
  );
}
