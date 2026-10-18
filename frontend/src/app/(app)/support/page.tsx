"use client";

import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { NoCompetition } from "@/components/app/no-competition";
import { NewTicketDialog } from "@/components/support/new-ticket-dialog";
import { StaffTicketView } from "@/components/support/staff-ticket-view";
import { TicketQueue } from "@/components/support/ticket-queue";
import { TicketThread } from "@/components/support/ticket-thread";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { useAuthStore } from "@/stores/auth";

// Support tickets (ROADMAP #18). Staff work the whole queue beside the open
// ticket (#503); a competitor sees only their own tickets, can open new ones,
// and reads a thread in a dialog. New tickets and replies cue staff / the other
// side over the WS rooms.
export default function SupportPage() {
  const { competitionId, data: competition } = useActiveCompetition();
  const access = useAccess();
  const isStaff = access.has("ticket_assign");

  if (!competitionId) {
    return <NoCompetition />;
  }
  if (isStaff) {
    // useSearchParams (the open ticket lives in the URL) needs a Suspense
    // boundary to keep the route renderable statically.
    return (
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <StaffSupport competitionId={competitionId} competitionName={competition?.name ?? ""} />
      </Suspense>
    );
  }
  return <CompetitorSupport competitionId={competitionId} competitionName={competition?.name ?? ""} />;
}

function StaffSupport({
  competitionId,
  competitionName,
}: {
  competitionId: string;
  competitionName: string;
}) {
  const tr = useTranslations("support");
  const ts = useTranslations("support.staff");
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const userId = useAuthStore((s) => s.user?.id);
  // The competition support room: the live queue + new-ticket cue.
  useSupportQueueLive(competitionId, true);
  const tickets = useTickets(competitionId);

  // The open ticket is in the URL, so a link to it can be shared with another
  // judge. Opening one adds a history entry and moving between tickets
  // replaces it, so Back returns to the queue rather than through every
  // ticket looked at.
  const selectedId = params.get("ticket");
  function select(id: string | null) {
    const next = new URLSearchParams(params.toString());
    if (id) next.set("ticket", id);
    else next.delete("ticket");
    const query = next.toString();
    const url = query ? `${pathname}?${query}` : pathname;
    if (id && selectedId) router.replace(url, { scroll: false });
    else router.push(url, { scroll: false });
  }

  const all = tickets.data ?? [];
  const open = all.filter((t) => t.status === "open").length;
  const waiting = all.filter((t) => t.awaiting_staff).length;

  return (
    <>
      <SectionHeader
        title={tr("title")}
        subtitle={`${competitionName} · ${ts("summary", { open, waiting })}`}
      />
      {tickets.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : all.length === 0 ? (
        <EmptyState
          icon={<TicketEmptyIcon />}
          title={tr("empty.staffTitle")}
          description={tr("empty.staffDescription")}
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)] lg:items-start">
          {/* On a phone the queue and the ticket take turns. */}
          <Card className={cn(selectedId && "hidden lg:block")}>
            <CardContent className="p-3">
              <TicketQueue
                tickets={all}
                selectedId={selectedId}
                onSelect={select}
                userId={userId}
              />
            </CardContent>
          </Card>
          <div className={cn("grid min-w-0 gap-2", !selectedId && "hidden lg:grid")}>
            {selectedId ? (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  className="justify-self-start lg:hidden"
                  onClick={() => select(null)}
                >
                  ← {ts("backToQueue")}
                </Button>
                <Card>
                  <CardContent className="p-4 md:p-5">
                    {/* Keyed, so a half-written reply never follows you to
                        another ticket. */}
                    <StaffTicketView key={selectedId} competitionId={competitionId} ticketId={selectedId} />
                  </CardContent>
                </Card>
              </>
            ) : (
              <EmptyState
                icon={<TicketEmptyIcon />}
                title={ts("pickTitle")}
                description={ts("pickDescription")}
              />
            )}
          </div>
        </div>
      )}
    </>
  );
}

type Filter = "all" | TicketStatus;

function CompetitorSupport({
  competitionId,
  competitionName,
}: {
  competitionId: string;
  competitionName: string;
}) {
  // `t` is a ticket in the loops below, so the translator is `tr`.
  const tr = useTranslations("support");
  const tn = useTranslations("common.nouns");
  const tickets = useTickets(competitionId);
  const [filter, setFilter] = useState<Filter>("all");
  const [openId, setOpenId] = useState<string | null>(null);

  const all = tickets.data ?? [];
  // Status tabs narrow first; the data-table hook then layers subject search +
  // pagination on top (#16 #20).
  const visible = all.filter((t) => filter === "all" || t.status === filter);
  const table = useDataTable(visible, {
    searchKeys: [(t: Ticket) => t.subject],
  });
  const filters: Filter[] = ["all", "open", "resolved"];

  return (
    <>
      <SectionHeader
        title={tr("title")}
        subtitle={`${competitionName} · ${tr("yourTickets")}`}
        actions={<NewTicketDialog competitionId={competitionId} />}
      />

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
              {tr(`status.${f}`)}
            </button>
          ))}
        </div>
        <TableSearchInput
          value={table.query}
          onChange={table.setQuery}
          placeholder={tr("searchPlaceholder")}
          className="mb-1.5"
        />
      </div>

      {tickets.isLoading && <Skeleton className="h-40 w-full" />}

      {!tickets.isLoading && all.length === 0 ? (
        <EmptyState
          icon={<TicketEmptyIcon />}
          title={tr("empty.competitorTitle")}
          description={tr("empty.competitorDescription")}
          action={<NewTicketDialog competitionId={competitionId} />}
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
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">{t.subject}</span>
                        {t.kind === "question" && (
                          <span className="shrink-0 rounded-full bg-primary/10 px-2 py-px text-[11px] font-medium text-primary">
                            {tr("questionTag")}
                          </span>
                        )}
                      </div>
                      <div className="truncate text-xs text-muted-foreground">
                        {tr("you")}
                        {t.challenge_title && ` · ${t.challenge_title}`}
                        {" · "}
                        {tr("messageCount", { count: t.message_count })}
                      </div>
                    </div>
                    <Badge variant={t.status === "open" ? "destructive" : "muted"}>
                      {t.kind === "question" ? tr(`questionStatus.${t.status}`) : tr(`status.${t.status}`)}
                    </Badge>
                  </button>
                </li>
              ))}
              {!tickets.isLoading && table.rows.length === 0 && (
                <li className="py-8 text-center text-sm text-muted-foreground">
                  {tr(table.query ? "noMatchSearch" : "noMatchFilter", {
                    filter: filter === "all" ? "" : `${tr(`status.${filter}`)} `,
                  })}
                </li>
              )}
            </ul>
            <TablePagination table={table} noun={tn("tickets")} className="mt-4" />
          </CardContent>
        </Card>
      )}

      <Dialog open={!!openId} onOpenChange={(o) => !o && setOpenId(null)}>
        <DialogContent>
          {openId && <TicketThread competitionId={competitionId} ticketId={openId} />}
        </DialogContent>
      </Dialog>
    </>
  );
}
