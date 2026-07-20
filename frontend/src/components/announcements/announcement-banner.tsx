"use client";

import * as React from "react";

import { useAnnouncements } from "@/lib/hooks/use-announcements";
import { useAuthStore } from "@/stores/auth";

// The live announcement banner (§4.3): the newest announcement for the active
// competition, pushed in real time over the announcements WS room and
// dismissible. Dismissal is keyed by id, so the next announcement re-shows.
export function AnnouncementBanner() {
  const competitionId = useAuthStore((s) => s.activeCompetitionId);
  const announcements = useAnnouncements(competitionId ?? "");
  const [dismissedId, setDismissedId] = React.useState<string | null>(null);

  const latest = announcements.data?.[0];
  if (!competitionId || !latest || latest.id === dismissedId) return null;

  return (
    <div className="flex items-start gap-3 border-b border-primary/30 bg-primary/10 px-8 py-2.5">
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
