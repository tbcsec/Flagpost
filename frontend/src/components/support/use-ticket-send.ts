"use client";

import { useTranslations } from "next-intl";

import {
  useClarifyTicket,
  useReplyTicket,
  useUploadTicketAttachment,
} from "@/lib/hooks/use-tickets";
import type { TicketDetail } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

/** How a message goes out: a reply the other side reads, a staff-only internal
 *  note, or an answer posted to everyone as a clarification (#450). */
export type SendMode = "reply" | "internal" | "everyone";

// Sending on a ticket, shared by the competitor's thread and the staff ticket
// view (#503): the reply or clarification, then any screenshots attached to the
// message just posted, with the same toasts either way.
export function useTicketSend(competitionId: string, ticketId: string) {
  const tr = useTranslations("support");
  const reply = useReplyTicket(competitionId, ticketId);
  const clarify = useClarifyTicket(competitionId, ticketId);
  const upload = useUploadTicketAttachment(competitionId);
  const userId = useAuthStore((s) => s.user?.id);

  function send(
    {
      mode,
      body,
      files = [],
      question = "",
    }: { mode: SendMode; body: string; files?: File[]; question?: string },
    { onSent }: { onSent: () => void },
  ) {
    const handlers = {
      onSuccess: async (detail: TicketDetail) => {
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
        onSent();
        if (mode === "everyone") {
          toast(tr("thread.sentToAllToast"), { variant: "success" });
        }
        if (failures.length > 0) {
          toast(tr("thread.replyPartialToast", { files: failures.join(", ") }), {
            variant: "destructive",
          });
        }
      },
    };
    // Only the error of what was just sent should show.
    if (mode === "everyone") {
      reply.reset();
      clarify.mutate({ question, answer: body }, handlers);
    } else {
      clarify.reset();
      reply.mutate({ body, is_internal: mode === "internal" }, handlers);
    }
  }

  const failed = reply.isError ? reply.error : clarify.isError ? clarify.error : null;
  return {
    send,
    sending: reply.isPending || clarify.isPending || upload.isPending,
    error: failed as Error | null,
  };
}
