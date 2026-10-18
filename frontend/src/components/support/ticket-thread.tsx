"use client";

import { useState } from "react";

import { useTranslations } from "next-intl";

import { PresenceIndicator } from "@/components/presence/presence-indicator";
import { ScreenshotPicker } from "@/components/support/screenshot-picker";
import { TicketMessageList } from "@/components/support/ticket-message-list";
import { useTicketSend } from "@/components/support/use-ticket-send";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { usePresence } from "@/lib/hooks/use-presence";
import { useTicket } from "@/lib/hooks/use-tickets";
import { useAuthStore } from "@/stores/auth";

// A competitor's live ticket thread (§4.4), in a dialog. Messages refetch over
// the ticket's WS room, so a judge's reply appears (and cues) without a manual
// refresh. Staff work tickets in their own view (StaffTicketView, #503).
// A question about a problem (#450) is read-only once asked: its answer comes
// back here, and a follow-up is a new question.
export function TicketThread({
  competitionId,
  ticketId,
  onAskAgain,
}: {
  competitionId: string;
  ticketId: string;
  /** Where a question's asker can ask a follow-up (the problem page). */
  onAskAgain?: () => void;
}) {
  const ticket = useTicket(competitionId, ticketId);
  const sender = useTicketSend(competitionId, ticketId);
  // "A judge is looking at this ticket" (§4.1).
  const presence = usePresence("ticket", ticketId);
  const userId = useAuthStore((s) => s.user?.id);
  // `t` is the ticket data below, so the translator is `tr` (whole `support`
  // namespace — it also needs the shared status labels).
  const tr = useTranslations("support");

  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);

  const t = ticket.data;
  const isQuestion = t?.kind === "question";
  // The 5-image cap is per ticket, so the picker has to count what's already on
  // the thread — not just what's staged on this reply. A competitor's thread
  // omits internal notes, so their count can undershoot; the server still
  // enforces the real cap (and we'd rather undershoot than disclose that staff
  // attached something to a note the competitor can't see).
  const attachedCount =
    t?.messages.reduce((n, m) => n + m.attachments.length, 0) ?? 0;

  function onReply(e: React.FormEvent) {
    e.preventDefault();
    sender.send(
      { mode: "reply", body, files },
      {
        onSent: () => {
          setBody("");
          setFiles([]);
        },
      },
    );
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t?.subject ?? tr("thread.fallbackTitle")}</DialogTitle>
        <DialogDescription>
          {t ? (
            <>
              {isQuestion && (
                <span className="mr-2 rounded-full bg-primary/10 px-2 py-px text-[11px] font-medium text-primary">
                  {tr("questionTag")}
                </span>
              )}
              <Badge variant={t.status === "open" ? "destructive" : "muted"}>
                {isQuestion ? tr(`questionStatus.${t.status}`) : tr(`status.${t.status}`)}
              </Badge>
              {t.challenge_title && <span className="ml-2">· {t.challenge_title}</span>}
              <span className="ml-2">· {t.team_name ?? t.opener_name}</span>
              {t.assignee_name && <span className="ml-2">{tr("thread.assignedTo", { name: t.assignee_name })}</span>}
            </>
          ) : (
            tr("thread.loading")
          )}
        </DialogDescription>
      </DialogHeader>

      {(presence.others.length > 0 || presence.staffPresent) && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/40 px-3 py-2">
          <span className="text-xs text-muted-foreground">
            {presence.staffPresent
              ? tr("thread.judgeLooking")
              : tr("thread.othersHere", { count: presence.others.length })}
          </span>
          <PresenceIndicator members={presence.others} max={5} />
        </div>
      )}

      {/* Taller than the original max-h-72: a message carrying screenshot
          thumbnails is ~100px taller than a text-only one, and the old height
          clipped the first image in the thread. */}
      <TicketMessageList
        competitionId={competitionId}
        ticketId={ticketId}
        messages={t?.messages ?? []}
        // Your own attachments only — the same rule the API enforces.
        canDelete={(a) => a.uploader_user_id === userId}
        className="max-h-96 overflow-y-auto pr-1"
      />

      {isQuestion ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted/50 px-3 py-2.5">
          <p className="text-sm text-muted-foreground">
            {t?.status === "resolved" ? tr("thread.questionAnswered") : tr("thread.questionWaiting")}
          </p>
          {onAskAgain && (
            <Button type="button" variant="outline" size="sm" onClick={onAskAgain}>
              {tr("thread.askAgain")}
            </Button>
          )}
        </div>
      ) : (
        <form onSubmit={onReply} className="grid gap-2">
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            required
            rows={3}
            aria-label={tr("thread.replyAria")}
            placeholder={tr("thread.replyPlaceholder")}
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          />
          <ScreenshotPicker
            files={files}
            onChange={setFiles}
            existingCount={attachedCount}
            disabled={sender.sending}
          />
          <div className="flex justify-end">
            <Button type="submit" size="sm" disabled={sender.sending}>
              {sender.sending ? tr("thread.sending") : tr("thread.send")}
            </Button>
          </div>
          {sender.error && (
            <p role="alert" className="text-sm text-destructive">{sender.error.message}</p>
          )}
        </form>
      )}
    </>
  );
}
