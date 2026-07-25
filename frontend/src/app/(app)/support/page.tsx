"use client";

import { useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { NoCompetition } from "@/components/app/no-competition";
import { NewTicketDialog } from "@/components/support/new-ticket-dialog";
import { TicketThread } from "@/components/support/ticket-thread";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { TablePagination, TableSearchInput } from "@/components/ui/data-table";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { EmptyState, TicketEmptyIcon } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useDataTable } from "@/lib/hooks/use-data-table";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useSupportQueueLive, useTickets } from "@/lib/hooks/use-tickets";
import type { Ticket, TicketStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

// Support tickets (ROADMAP #18). Staff see the whole queue with stats + filter
// tabs; a competitor sees only their own tickets and can open new ones. Both
// open the live thread. New tickets and replies cue staff / the other side
// over the WS rooms.
type Filter = "all" | TicketStatus;

export default function SupportPage() {
  const { competitionId, data: competition } = useActiveCompetition();
  const access = useAccess();
  const isStaff = access.has("ticket_assign");

  // Staff subscribe to the competition support room (live queue + new-ticket cue).
  useSupportQueueLive(competitionId ?? "", isStaff);

  const tickets = useTickets(competitionId ?? "");
  const [filter, setFilter] = useState<Filter>("all");
  const [openId, setOpenId] = useState<string | null>(null);

  const all = tickets.data ?? [];
  const openCount = all.filter((t) => t.status === "open").length;
  const resolvedCount = all.filter((t) => t.status === "resolved").length;
  // Status tabs narrow first; the data-table hook then layers subject search +
  // pagination on top (#16 #20). Headless, so it drives this card list the same
  // way it drives real tables. Declared before the early return — hook rules.
  const visible = all.filter((t) => filter === "all" || t.status === filter);
  const table = useDataTable(visible, {
    searchKeys: [(t: Ticket) => t.subject],
  });

  if (!competitionId) {
    return <NoCompetition />;
  }

  const filters: Filter[] = ["all", "open", "resolved"];

  return (
    <>
      <SectionHeader
        title="Support"
        subtitle={`${competition?.name ?? ""} · ${isStaff ? `${openCount} open` : "your tickets"}`}
        actions={!isStaff ? <NewTicketDialog competitionId={competitionId} /> : undefined}
      />

      {isStaff && (
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: "All tickets", value: all.length },
            { label: "Open", value: openCount },
            { label: "Resolved", value: resolvedCount },
          ].map((s) => (
            <Card key={s.label}>
              <CardContent className="p-6 text-center">
                <div className="text-xs text-muted-foreground">{s.label}</div>
                <div className="mt-1 font-display text-2xl font-semibold tracking-tight">{s.value}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between gap-3 border-b border-border">
        <div className="flex gap-2">
          {filters.map((f) => (
            <button
              key={f}
              onClick={() => {
                setFilter(f);
                table.setPage(0);
              }}
              className={cn(
                "-mb-px border-b-2 px-1 py-2.5 text-sm capitalize transition-colors",
                filter === f
                  ? "border-primary font-semibold text-foreground"
                  : "border-transparent font-medium text-muted-foreground",
              )}
            >
              {f}
            </button>
          ))}
        </div>
        <TableSearchInput
          value={table.query}
          onChange={table.setQuery}
          placeholder="Search tickets…"
          className="mb-1.5"
        />
      </div>

      {tickets.isLoading && <Skeleton className="h-40 w-full" />}

      {!tickets.isLoading && all.length === 0 ? (
        <EmptyState
          icon={<TicketEmptyIcon />}
          title={isStaff ? "No tickets yet" : "Need a hand?"}
          description={
            isStaff
              ? "When competitors open support tickets they'll appear here — you'll get a cue the moment one lands."
              : "Stuck on a challenge or hit a snag? Open a ticket and staff will pick it up live."
          }
          action={!isStaff ? <NewTicketDialog competitionId={competitionId} /> : undefined}
        />
      ) : (
      <Card>
        <CardContent className="pt-5">
          <ul className="grid">
            {table.rows.map((t) => (
              <li key={t.id}>
                <button
                  onClick={() => setOpenId(t.id)}
                  className="flex w-full items-center justify-between gap-3 border-b border-border py-3 text-left last:border-0 hover:bg-accent/40"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{t.subject}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      {isStaff ? (t.team_name ?? t.opener_name) : "You"}
                      {t.challenge_title && ` · ${t.challenge_title}`}
                      {` · ${t.message_count} message${t.message_count === 1 ? "" : "s"}`}
                    </div>
                  </div>
                  <Badge variant={t.status === "open" ? "destructive" : "muted"}>{t.status}</Badge>
                </button>
              </li>
            ))}
            {!tickets.isLoading && table.rows.length === 0 && (
              <li className="py-8 text-center text-sm text-muted-foreground">
                No {filter === "all" ? "" : `${filter} `}tickets match
                {table.query ? " your search" : " this filter"}.
              </li>
            )}
          </ul>
          <TablePagination table={table} noun="tickets" className="mt-4" />
        </CardContent>
      </Card>
      )}

      <Dialog open={!!openId} onOpenChange={(o) => !o && setOpenId(null)}>
        <DialogContent>
          {openId && (
            <TicketThread competitionId={competitionId} ticketId={openId} isStaff={isStaff} />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
