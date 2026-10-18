"use client";

import { useTranslations } from "next-intl";

import { TicketAttachments } from "@/components/support/ticket-attachments";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import type { TicketAttachment, TicketMessage } from "@/lib/types";
import { cn } from "@/lib/utils";

// A ticket's messages, oldest first — shared by the competitor's thread and the
// staff ticket view (#503). Internal notes (staff only; the server leaves them
// out for anyone else) read in the warning tone, answers that went to everyone
// say so, and a withdrawn one is struck through for staff (a competitor no
// longer gets its text).
export function TicketMessageList({
  competitionId,
  ticketId,
  messages,
  canDelete,
  className,
}: {
  competitionId: string;
  ticketId: string;
  messages: TicketMessage[];
  canDelete: (attachment: TicketAttachment) => boolean;
  className?: string;
}) {
  const tr = useTranslations("support");
  const rel = useRelativeTime();
  return (
    <ul className={cn("grid gap-3", className)}>
      {messages.map((m) => (
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
              {m.is_internal && (
                <span className="ml-2 text-[11px] text-warning">{tr("thread.internalNote")}</span>
              )}
              {m.sent_to_all && (
                <span
                  className={cn(
                    "ml-2 text-[11px]",
                    m.withdrawn ? "text-muted-foreground" : "text-primary",
                  )}
                >
                  {m.withdrawn ? tr("thread.sentToAllWithdrawn") : tr("thread.sentToAll")}
                </span>
              )}
            </span>
            <span className="whitespace-nowrap text-[11px] text-muted-foreground">
              {rel(m.created_at)}
            </span>
          </div>
          {m.body && (
            <p
              className={cn(
                // A hash, base64 or URL in a ticket mustn't widen the page.
                "mt-1 whitespace-pre-line text-sm [overflow-wrap:anywhere]",
                m.withdrawn ? "text-muted-foreground line-through" : "text-foreground",
              )}
            >
              {m.body}
            </p>
          )}
          <TicketAttachments
            competitionId={competitionId}
            ticketId={ticketId}
            attachments={m.attachments}
            canDelete={canDelete}
          />
        </li>
      ))}
    </ul>
  );
}
