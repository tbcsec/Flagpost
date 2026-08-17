"use client";

import { useState } from "react";

import { useTranslations } from "next-intl";
import dynamic from "next/dynamic";

import { PresenceIndicator } from "@/components/presence/presence-indicator";
import { ScreenshotPicker } from "@/components/support/screenshot-picker";
import { TicketAttachments } from "@/components/support/ticket-attachments";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import { usePresence } from "@/lib/hooks/use-presence";
import {
  useAssignTicket,
  useReplyTicket,
  useResolveTicket,
  useTicket,
  useUploadTicketAttachment,
} from "@/lib/hooks/use-tickets";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
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
  const upload = useUploadTicketAttachment(competitionId);
  const userId = useAuthStore((s) => s.user?.id);
  // `t` is the ticket data below, so the translator is `tr` (whole `support`
  // namespace — it also needs the shared status labels).
  const tr = useTranslations("support");
  const rel = useRelativeTime();

  const [body, setBody] = useState("");
  const [internal, setInternal] = useState(false);
  const [files, setFiles] = useState<File[]>([]);

  const t = ticket.data;
  // The 5-image cap is per ticket, so the picker has to count what's already on
  // the thread — not just what's staged on this reply. A competitor's thread
  // omits internal notes, so their count can undershoot; the server still
  // enforces the real cap (and we'd rather undershoot than disclose that staff
  // attached something to a note the competitor can't see).
  const attachedCount =
    t?.messages.reduce((n, m) => n + m.attachments.length, 0) ?? 0;

  function onReply(e: React.FormEvent) {
    e.preventDefault();
    reply.mutate(
      { body, is_internal: internal },
      {
        onSuccess: async (detail) => {
          // The reply we just posted is our own most recent message — safer
          // than taking the last message outright, which could be someone
          // else's if they posted while this request was in flight.
          const messageId = detail.messages
            .filter((m) => m.author_user_id === userId)
            .at(-1)?.id;
          // If we somehow can't identify the message we just posted, the
          // screenshots have nowhere to go — say so rather than dropping them
          // silently behind a success message.
          const failures: string[] = messageId ? [] : files.map((f) => f.name);
          if (messageId) {
            for (const file of files) {
              try {
                await upload.mutateAsync({ ticketId, messageId, file });
              } catch {
                failures.push(file.name);
              }
            }
          }
          setBody("");
          setInternal(false);
          setFiles([]);
          if (failures.length > 0) {
            toast(tr("thread.replyPartialToast", { files: failures.join(", ") }), {
              variant: "destructive",
            });
          }
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
              <Badge variant={t.status === "open" ? "destructive" : "muted"}>{tr(`status.${t.status}`)}</Badge>
              {t.challenge_title && <span className="ml-2">· {t.challenge_title}</span>}
              <span className="ml-2">· {t.team_name ?? t.opener_name}</span>
              {t.assignee_name && <span className="ml-2">{tr("thread.assignedTo", { name: t.assignee_name })}</span>}
            </>
          ) : (
            tr("thread.loading")
          )}
        </DialogDescription>
      </DialogHeader>

      {(presence.others.length > 0 || (!isStaff && presence.staffPresent)) && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/40 px-3 py-2">
          <span className="text-xs text-muted-foreground">
            {!isStaff && presence.staffPresent
              ? tr("thread.judgeLooking")
              : tr("thread.othersHere", { count: presence.others.length })}
          </span>
          <PresenceIndicator members={presence.others} max={5} />
        </div>
      )}

      {/* Taller than the original max-h-72: a message carrying screenshot
          thumbnails is ~100px taller than a text-only one, and the old height
          clipped the first image in the thread. */}
      <ul className="grid max-h-96 gap-3 overflow-y-auto pr-1">
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
                {m.is_internal && <span className="ml-2 text-[11px] text-warning">{tr("thread.internalNote")}</span>}
              </span>
              <span className="whitespace-nowrap text-[11px] text-muted-foreground">
                {rel(m.created_at)}
              </span>
            </div>
            <p className="mt-1 whitespace-pre-line text-sm text-foreground">{m.body}</p>
            <TicketAttachments
              competitionId={competitionId}
              ticketId={ticketId}
              attachments={m.attachments}
              // Your own, or anyone's if you're staff (moderation) — the same
              // rule the API enforces.
              canDelete={(a) => isStaff || a.uploader_user_id === userId}
            />
          </li>
        ))}
      </ul>

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
          disabled={reply.isPending || upload.isPending}
        />
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            {isStaff && (
              <label className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
                <input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} />
                {tr("thread.internalCheckbox")}
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
                  onClick={() => assign.mutate(undefined, { onSuccess: () => toast(tr("thread.assignedToast")) })}
                >
                  {tr("thread.assignToMe")}
                </Button>
                {t?.status === "open" && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={resolve.isPending}
                    onClick={() => resolve.mutate(undefined, { onSuccess: () => toast(tr("thread.resolvedToast"), { variant: "success" }) })}
                  >
                    {tr("thread.resolve")}
                  </Button>
                )}
              </>
            )}
            <Button
              type="submit"
              size="sm"
              disabled={reply.isPending || upload.isPending}
            >
              {reply.isPending || upload.isPending ? tr("thread.sending") : tr("thread.send")}
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
            <h3 className="text-sm font-medium">{tr("thread.staffNotes")}</h3>
            <p className="text-xs text-muted-foreground">
              {tr("thread.staffNotesDesc")}
            </p>
          </div>
          <CollabNote docKey={`ticket:${ticketId}`} />
        </section>
      )}
    </>
  );
}
