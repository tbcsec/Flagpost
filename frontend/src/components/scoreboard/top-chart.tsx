"use client";

import { useState } from "react";

import { RankBadge } from "@/components/scoreboard/rank-badge";
import { relativeTime } from "@/lib/datetime";
import type { ScoreboardEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

// The top-10 bar chart on the authenticated scoreboard (#52). The bars alone
// said nothing without scanning the table below, so each column now carries its
// context three ways:
//
// - at a glance: points above the bar, rank + truncated name under it;
// - on hover/focus: a detail tooltip (full name, medal rank, points, last
//   solve, division, "you" marker). Revealed by React state off focus/hover —
//   not a CSS :hover/:focus trick — so a keyboard Tab and a mobile tap
//   (tap = focus on a button) open it identically, and tests can assert the
//   reveal rather than trusting a pseudo-class;
// - to a screen reader: an aria-label on the column with the same facts as
//   the tooltip, so parity doesn't depend on a visual layer.
//
// Hand-rolled like every chart here (§9 tokens, no tooltip/chart library).

// Bars scale to this fraction of the plot so the tallest bar still leaves room
// for its points label above it.
const HEADROOM = 0.86;

function label(entry: ScoreboardEntry, mine: boolean, isTeam: boolean): string {
  const parts = [
    `Rank ${entry.rank}: ${entry.name}${mine ? (isTeam ? " (your team)" : " (you)") : ""}`,
    `${entry.points} points`,
    entry.last_solve_at
      ? `last solve ${relativeTime(entry.last_solve_at)}`
      : "no solves yet",
  ];
  if (entry.bracket) parts.push(`division ${entry.bracket}`);
  return parts.join(", ");
}

export function TopChart({
  entries,
  mySubjectId,
  isTeam,
}: {
  /** Rank-ordered top slice of the board (the page passes the top 10). */
  entries: ScoreboardEntry[];
  mySubjectId: string | null | undefined;
  isTeam: boolean;
}) {
  const maxPoints = Math.max(1, ...entries.map((e) => e.points));
  // Which column's tooltip is open (subject id). One at a time, cleared on
  // leave/blur — hover and keyboard focus share the same state on purpose.
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <div className="flex h-44 items-end gap-2.5">
      {entries.map((entry, i) => {
        const pct = Math.round((entry.points / maxPoints) * 100 * HEADROOM);
        const mine = entry.subject_id === mySubjectId;
        // Edge columns anchor their tooltip to the nearest edge instead of
        // centring, so the first/last tooltips can't clip outside the card.
        const align =
          i < 2 ? "left-0" : i >= entries.length - 2 ? "right-0" : "left-1/2 -translate-x-1/2";
        const open = openId === entry.subject_id;
        return (
          <button
            type="button"
            key={entry.subject_id}
            aria-label={label(entry, mine, isTeam)}
            onMouseEnter={() => setOpenId(entry.subject_id)}
            onMouseLeave={() => setOpenId((id) => (id === entry.subject_id ? null : id))}
            onFocus={() => setOpenId(entry.subject_id)}
            onBlur={() => setOpenId((id) => (id === entry.subject_id ? null : id))}
            className="group relative flex h-full flex-1 cursor-default flex-col items-center justify-end gap-1.5 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {/* Detail tooltip. aria-hidden: the column's aria-label already
                carries these facts, so this is the sighted-user layer only. */}
            <div
              aria-hidden="true"
              data-open={open || undefined}
              className={cn(
                "pointer-events-none absolute bottom-full z-10 mb-1.5 w-max max-w-56 rounded-md border border-border bg-popover px-3 py-2 text-left text-popover-foreground shadow-lg transition-opacity duration-150",
                open ? "opacity-100" : "opacity-0",
                align,
              )}
            >
              <div className="flex items-center gap-2">
                <RankBadge rank={entry.rank} />
                <span className="text-[13px] font-medium">
                  {entry.name}
                  {mine && (
                    <span className="ml-1.5 text-[11px] text-primary">
                      {isTeam ? "your team" : "you"}
                    </span>
                  )}
                </span>
              </div>
              <div className="mt-1.5 grid gap-0.5 text-[11px] text-muted-foreground">
                <span>
                  <span className="font-mono text-foreground">{entry.points}</span> points
                </span>
                <span>
                  {entry.last_solve_at
                    ? `Last solve ${relativeTime(entry.last_solve_at)}`
                    : "No solves yet"}
                </span>
                {entry.bracket && <span>Division: {entry.bracket}</span>}
              </div>
            </div>

            {/* Plot area: the bar, with its points figure floated just above. */}
            <div className="relative flex w-full flex-1 items-end">
              <span
                aria-hidden="true"
                className="absolute w-full truncate text-center font-mono text-[10px] leading-none text-muted-foreground"
                style={{ bottom: `calc(${pct}% + 4px)` }}
              >
                {entry.points}
              </span>
              <div
                className={cn(
                  "w-full rounded-t transition-[height] duration-500",
                  mine ? "bg-primary" : "bg-secondary",
                  open && "opacity-90",
                )}
                style={{ height: `${pct}%` }}
              />
            </div>

            {/* Rank above name, stacked — side by side read too cramped in a
                tenth-width column (owner call). */}
            <span
              aria-hidden="true"
              className="grid w-full justify-items-center gap-0.5 text-[10px] leading-tight text-muted-foreground"
            >
              <span className="font-mono">{entry.rank}</span>
              <span className="max-w-full truncate">{entry.name}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
