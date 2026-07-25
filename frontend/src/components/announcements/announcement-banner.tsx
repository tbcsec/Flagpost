"use client";

import * as React from "react";

import { useAnnouncements } from "@/lib/hooks/use-announcements";
import { useAuthStore } from "@/stores/auth";

// The live announcement banner (§4.3): the newest announcement for the active
// competition, pushed in real time over the announcements WS room. Dismissal is
// keyed by id, so the next announcement re-shows; each announcement also
// auto-dismisses after a short dwell (#19) so the banner never sits stale or
// appears to "block" the ones behind it. The wrapper is keyed by announcement
// id so back-to-back announcements with identical text still visibly re-enter.
const AUTO_DISMISS_MS = 30_000;

export function AnnouncementBanner() {
  const competitionId = useAuthStore((s) => s.activeCompetitionId);
  const announcements = useAnnouncements(competitionId ?? "");
  const [dismissedId, setDismissedId] = React.useState<string | null>(null);

  const latest = announcements.data?.[0];
  const latestId = latest?.id ?? null;

  // Auto-dismiss the current announcement after its dwell time. Keyed to the
  // announcement id: a newer arrival resets the clock for the new content.
  React.useEffect(() => {
    if (!latestId) return;
    const t = setTimeout(() => setDismissedId(latestId), AUTO_DISMISS_MS);
    return () => clearTimeout(t);
  }, [latestId]);

  if (!competitionId || !latest || latest.id === dismissedId) return null;

  return (
    <div
      key={latest.id}
      className="anim-fade flex items-start gap-3 border-b border-primary/30 bg-primary/10 px-8 py-2.5"
    >
      <span className="mt-0.5 text-[11px] font-semibold uppercase tracking-wide text-primary">
        Announcement
      </span>
      <div className="min-w-0 flex-1">
        <span className="text-sm font-medium">{latest.title}</span>
        <span className="ml-2 text-sm text-muted-foreground">{latest.body}</span>
      </div>
      <button
        onClick={() => setDismissedId(latest.id)}
        className="flex-shrink-0 text-muted-foreground hover:text-foreground"
        aria-label="Dismiss announcement"
      >
        ×
      </button>
    </div>
  );
}
