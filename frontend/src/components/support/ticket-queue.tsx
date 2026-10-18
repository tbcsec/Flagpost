"use client";

import { useState } from "react";

import { useTranslations } from "next-intl";

import { TablePagination, TableSearchInput } from "@/components/ui/data-table";
import { useDataTable } from "@/lib/hooks/use-data-table";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import type { Ticket } from "@/lib/types";
import { cn } from "@/lib/utils";

// The staff ticket queue (#503), built for triage: who's waiting on staff, whose
// ticket it is, how long since it moved — without opening each one. A status
// tab, then one quick filter, then the search narrow the list.

export type QueueStatus = "open" | "resolved" | "all";
export type QueueFocus = "waiting" | "mine" | "unassigned";

/** The tickets a queue view shows, most recently active first. */
export function filterQueue(
  tickets: Ticket[],
  { status, focus, userId }: { status: QueueStatus; focus: QueueFocus | null; userId?: string },
): Ticket[] {
  return tickets
    .filter((t) => status === "all" || t.status === status)
    .filter((t) => {
      if (focus === "waiting") return t.awaiting_staff;
      if (focus === "mine") return Boolean(userId) && t.assignee_user_id === userId;
      if (focus === "unassigned") return t.status === "open" && !t.assignee_user_id;
      return true;
    })
    .sort((a, b) =>
      (b.last_activity_at ?? b.created_at).localeCompare(a.last_activity_at ?? a.created_at),
    );
}

export function TicketQueue({
  tickets,
  selectedId,
  onSelect,
  userId,
}: {
  tickets: Ticket[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  userId?: string;
}) {
  const tr = useTranslations("support");
  const ts = useTranslations("support.staff");
  const tn = useTranslations("common.nouns");
  const rel = useRelativeTime();
  const [status, setStatus] = useState<QueueStatus>("open");
  const [focus, setFocus] = useState<QueueFocus | null>(null);

  const visible = filterQueue(tickets, { status, focus, userId });
  const table = useDataTable(visible, { searchKeys: [(t: Ticket) => t.subject], initialPageSize: 10 });
  // The quick filters count across open work, whatever tab is showing.
  const counts: Record<QueueFocus, number> = {
    waiting: tickets.filter((t) => t.awaiting_staff).length,
    mine: tickets.filter((t) => t.status === "open" && Boolean(userId) && t.assignee_user_id === userId).length,
    unassigned: tickets.filter((t) => t.status === "open" && !t.assignee_user_id).length,
  };

  // minmax(0, 1fr) tracks: a truncated subject's min-content is its whole
  // length, which would otherwise push the queue past its column.
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3">
      <div role="tablist" aria-label={ts("statusLabel")} className="flex gap-1 border-b border-border">
        {(["open", "resolved", "all"] as const).map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={status === s}
            onClick={() => {
              setStatus(s);
              table.setPage(0);
            }}
            className={cn(
              "-mb-px border-b-2 px-2.5 py-2 text-sm capitalize transition-colors",
              status === s
                ? "border-primary font-semibold text-foreground"
                : "border-transparent font-medium text-muted-foreground hover:text-foreground",
            )}
          >
            {tr(`status.${s}`)}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-1.5" aria-label={ts("focusLabel")} role="group">
        {(["waiting", "mine", "unassigned"] as const).map((f) => (
          <button
            key={f}
            type="button"
            aria-pressed={focus === f}
            onClick={() => {
              setFocus(focus === f ? null : f);
              table.setPage(0);
            }}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
              focus === f
                ? "border-foreground bg-foreground text-background"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {ts(`focus.${f}`)}
            <span className="tabular-nums">{counts[f]}</span>
          </button>
        ))}
      </div>

      <TableSearchInput
        value={table.query}
        onChange={table.setQuery}
        placeholder={tr("searchPlaceholder")}
      />

      <ul className="grid grid-cols-[minmax(0,1fr)] gap-1">
        {table.rows.map((t) => (
          <li key={t.id}>
            <button
              type="button"
              onClick={() => onSelect(t.id)}
              aria-current={t.id === selectedId ? "true" : undefined}
              className={cn(
                "w-full rounded-md border px-3 py-2.5 text-left transition-colors hover:bg-accent/40",
                t.id === selectedId ? "border-primary/60 bg-accent/60" : "border-transparent",
              )}
            >
              <div className="flex items-center gap-2">
                {t.awaiting_staff && (
                  <span
                    className="h-2 w-2 shrink-0 rounded-full bg-warning"
                    role="img"
                    aria-label={ts("waiting")}
                  />
                )}
                <span className="truncate text-sm font-medium">{t.subject}</span>
                {t.kind === "question" && (
                  <span className="shrink-0 rounded-full bg-primary/10 px-2 py-px text-[11px] font-medium text-primary">
                    {tr("questionTag")}
                  </span>
                )}
              </div>
              <div className="mt-0.5 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span className="truncate">
                  {t.team_name ?? t.opener_name}
                  {t.challenge_title && ` · ${t.challenge_title}`}
                </span>
                <span className="shrink-0">{rel(t.last_activity_at ?? t.created_at)}</span>
              </div>
              <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                {t.assignee_name ?? ts("unassigned")}
                {status === "all" &&
                  ` · ${t.kind === "question" ? tr(`questionStatus.${t.status}`) : tr(`status.${t.status}`)}`}
              </div>
            </button>
          </li>
        ))}
        {table.rows.length === 0 && (
          <li className="px-3 py-8 text-center text-sm text-muted-foreground">
            {table.query ? ts("noMatchSearch") : ts("noMatch")}
          </li>
        )}
      </ul>
      <TablePagination table={table} noun={tn("tickets")} />
    </div>
  );
}
