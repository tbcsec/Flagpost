"use client";

import { useState } from "react";

import dynamic from "next/dynamic";

import { PresenceIndicator } from "@/components/presence/presence-indicator";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { relativeTime } from "@/lib/datetime";
import { usePresence } from "@/lib/hooks/use-presence";
import {
  useAssignTicket,
  useReplyTicket,
  useResolveTicket,
  useTicket,
} from "@/lib/hooks/use-tickets";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast";

// The staff notes pad pulls TipTap + Y.js — load it only when a staff viewer
// actually renders the thread, not in every competitor's support bundle.
const CollabNote = dynamic(
  () => import("@/components/collab/collab-note").then((m) => m.CollabNote),
  { ssr: false, loading: () => <Skeleton className="h-32 w-full" /> },
);

// The live ticket thread (§4.4). Messages refetch over the ticket's WS room, so
// a reply from the other side appears (and cues) without a manual refresh.
// Staff (isStaff) get assign/resolve and can post internal notes.
export function TicketThread({
  competitionId,
  ticketId,
  isStaff,
}: {
  competitionId: string;
  ticketId: string;
  isStaff: boolean;
}) {
  const ticket = useTicket(competitionId, ticketId);
  const reply = useReplyTicket(competitionId, ticketId);
  const assign = useAssignTicket(competitionId, ticketId);
  const resolve = useResolveTicket(competitionId, ticketId);
  // Who else is on this thread live (§4.1). A competitor sees "a judge is
  // looking"; staff see the other people currently on the ticket.
  const presence = usePresence("ticket", ticketId);

  const [body, setBody] = useState("");
  const [internal, setInternal] = useState(false);

  const t = ticket.data;

  function onReply(e: React.FormEvent) {
    e.preventDefault();
    reply.mutate(
      { body, is_internal: internal },
      { onSuccess: () => { setBody(""); setInternal(false); } },
    );
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t?.subject ?? "Ticket"}</DialogTitle>
        <DialogDescription>
          {t ? (
            <>
              <Badge variant={t.status === "open" ? "destructive" : "muted"}>{t.status}</Badge>
              {t.challenge_title && <span className="ml-2">· {t.challenge_title}</span>}
              <span className="ml-2">· {t.team_name ?? t.opener_name}</span>
              {t.assignee_name && <span className="ml-2">· assigned to {t.assignee_name}</span>}
            </>
          ) : (
            "Loading…"
          )}
        </DialogDescription>
      </DialogHeader>

      {(presence.others.length > 0 || (!isStaff && presence.staffPresent)) && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/40 px-3 py-2">
          <span className="text-xs text-muted-foreground">
            {!isStaff && presence.staffPresent
              ? "A judge is looking at this ticket"
              : `${presence.others.length} other${presence.others.length === 1 ? "" : "s"} here`}
          </span>
          <PresenceIndicator members={presence.others} max={5} />
        </div>
      )}

      <ul className="grid max-h-72 gap-3 overflow-y-auto pr-1">
        {t?.messages.map((m) => (
          <li
            key={m.id}
            className={cn(
              "rounded-md border p-3",
              m.is_internal ? "border-warning/40 bg-warning/10" : "border-border",
            )}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[13px] font-medium">
                {m.author_name}
                {m.is_internal && <span className="ml-2 text-[11px] text-warning">internal note</span>}
              </span>
              <span className="whitespace-nowrap text-[11px] text-muted-foreground">
                {relativeTime(m.created_at)}
              </span>
            </div>
            <p className="mt-1 whitespace-pre-line text-sm text-foreground">{m.body}</p>
          </li>
        ))}
      </ul>

      <form onSubmit={onReply} className="grid gap-2">
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          required
          rows={3}
          aria-label="Reply"
          placeholder="Write a reply…"
          className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        />
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            {isStaff && (
              <label className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
                <input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} />
                Internal note
              </label>
            )}
          </div>
          <div className="flex items-center gap-2">
            {isStaff && (
              <>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={assign.isPending}
                  onClick={() => assign.mutate(undefined, { onSuccess: () => toast("Assigned to you") })}
                >
                  Assign to me
                </Button>
                {t?.status === "open" && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={resolve.isPending}
                    onClick={() => resolve.mutate(undefined, { onSuccess: () => toast("Ticket resolved", { variant: "success" }) })}
                  >
                    Resolve
                  </Button>
                )}
              </>
            )}
            <Button type="submit" size="sm" disabled={reply.isPending}>
              {reply.isPending ? "Sending…" : "Send"}
            </Button>
          </div>
        </div>
        {reply.isError && (
          <p role="alert" className="text-sm text-destructive">{(reply.error as Error).message}</p>
        )}
      </form>

      {isStaff && (
        <section className="grid gap-2 border-t border-border pt-3">
          <div>
            <h3 className="text-sm font-medium">Staff notes</h3>
            <p className="text-xs text-muted-foreground">
              A shared working pad for staff on this ticket — never shown to the competitor, live as you type.
            </p>
          </div>
          <CollabNote docKey={`ticket:${ticketId}`} />
        </section>
      )}
    </>
  );
}
