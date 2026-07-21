"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { relativeTime } from "@/lib/datetime";
import {
  useAssignTicket,
  useReplyTicket,
  useResolveTicket,
  useTicket,
} from "@/lib/hooks/use-tickets";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast";

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
          <p className="text-sm text-destructive">{(reply.error as Error).message}</p>
        )}
      </form>
    </>
  );
}
