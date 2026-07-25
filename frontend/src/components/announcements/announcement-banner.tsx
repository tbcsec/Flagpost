"use client";

import * as React from "react";

import { severityStyle } from "@/lib/announcement-severity";
import { useAnnouncements } from "@/lib/hooks/use-announcements";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";

// The live announcement banner (§4.3): the newest announcement for the active
// competition, pushed in real time over the announcements WS room. Dismissal is
// keyed by id, so the next announcement re-shows; ordinary announcements also
// auto-dismiss after a short dwell (#19) so the banner never sits stale or
// appears to "block" the ones behind it. A `critical` announcement (#40) never
// auto-dismisses — it stays until the reader closes it. The wrapper is keyed by
// announcement id so back-to-back announcements with identical text still
// visibly re-enter.

/** Severity glyphs — inline SVG, matching the app's icon idiom (no icon lib). */
function SeverityIcon({ severity }: { severity: string }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  if (severity === "critical") {
    // Octagon — the strongest "stop and read this" shape.
    return (
      <svg {...common}>
        <path d="M7.9 2.5h8.2L21.5 7.9v8.2L16.1 21.5H7.9L2.5 16.1V7.9z" />
        <line x1="12" y1="8" x2="12" y2="13" />
        <line x1="12" y1="16.5" x2="12" y2="16.5" />
      </svg>
    );
  }
  if (severity === "warning") {
    return (
      <svg {...common}>
        <path d="M10.3 3.9 1.9 18a2 2 0 0 0 1.7 3h16.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12" y2="17" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="9.5" />
      <line x1="12" y1="11" x2="12" y2="16.5" />
      <line x1="12" y1="7.5" x2="12" y2="7.5" />
    </svg>
  );
}

export function AnnouncementBanner() {
  const competitionId = useAuthStore((s) => s.activeCompetitionId);
  const announcements = useAnnouncements(competitionId ?? "");
  const [dismissedId, setDismissedId] = React.useState<string | null>(null);

  const latest = announcements.data?.[0];
  const latestId = latest?.id ?? null;
  const style = severityStyle(latest?.severity);
  const dwell = style.autoDismissMs;

  // Auto-dismiss the current announcement after its dwell time. Keyed to the
  // announcement id, so a newer arrival resets the clock for the new content;
  // a null dwell (critical) never schedules one.
  React.useEffect(() => {
    if (!latestId || dwell == null) return;
    const t = setTimeout(() => setDismissedId(latestId), dwell);
    return () => clearTimeout(t);
  }, [latestId, dwell]);

  if (!competitionId || !latest || latest.id === dismissedId) return null;

  return (
    <div
      key={latest.id}
      role={latest.severity === "critical" ? "alert" : "status"}
      className={cn(
        // Left accent bar carries the severity at a glance.
        "anim-fade flex items-start gap-3 border-b border-l-4 py-3 pl-5 pr-4 md:pl-6",
        style.surface,
      )}
    >
      <span className={cn("mt-0.5 flex-shrink-0", style.accent)}>
        <SeverityIcon severity={latest.severity} />
      </span>
      <div className="min-w-0 flex-1">
        <div
          className={cn(
            "text-[11px] font-semibold uppercase tracking-wide",
            style.accent,
          )}
        >
          {style.label}
        </div>
        <div className="mt-0.5 text-sm font-semibold leading-snug">
          {latest.title}
        </div>
        <div className="mt-0.5 text-sm leading-snug text-muted-foreground">
          {latest.body}
        </div>
      </div>
      <button
        onClick={() => setDismissedId(latest.id)}
        className="-mr-1 flex-shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-foreground/10 hover:text-foreground"
        aria-label="Dismiss announcement"
      >
        <svg
          aria-hidden="true"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
        >
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  );
}
