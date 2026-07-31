"use client";

// Inline screenshot previews on a ticket message (issue #80) — staff shouldn't
// have to download a file to see what a competitor is describing, and the
// opener sees their own attachments the same way.
//
// Bytes arrive as a `blob:` URL from useAttachmentImage rather than a storage
// URL: the API requires a Bearer header, and the production CSP only allows
// `img-src 'self' data: blob:`, so a presigned cross-origin URL wouldn't render.

import { useState } from "react";

import { formatSize } from "@/components/support/screenshot-picker";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import {
  useAttachmentImage,
  useDeleteTicketAttachment,
} from "@/lib/hooks/use-tickets";
import type { TicketAttachment } from "@/lib/types";

function Thumbnail({
  competitionId,
  ticketId,
  attachment,
  onOpen,
}: {
  competitionId: string;
  ticketId: string;
  attachment: TicketAttachment;
  onOpen: () => void;
}) {
  const { url, failed } = useAttachmentImage(competitionId, ticketId, attachment.id);

  if (failed) {
    return (
      <span className="flex h-20 w-20 items-center justify-center rounded-md border border-border bg-muted/40 p-1 text-center text-[10px] text-muted-foreground">
        Preview unavailable
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={onOpen}
      title={`${attachment.filename} · ${formatSize(attachment.size_bytes)}`}
      aria-label={`View ${attachment.filename} full size`}
      className="h-20 w-20 overflow-hidden rounded-md border border-border bg-muted/40 transition-colors hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      {url ? (
        // A blob: URL can't go through next/image's optimizer, and the bytes are
        // already local — there's nothing for it to optimize.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={url}
          alt={attachment.filename}
          className="h-full w-full object-cover"
        />
      ) : (
        <span className="flex h-full w-full animate-pulse bg-muted" />
      )}
    </button>
  );
}

/** The full-size view. Mounted only while open so its blob is fetched on demand
 *  and revoked on close, rather than held for every attachment in the thread. */
function Lightbox({
  competitionId,
  ticketId,
  attachment,
  onClose,
}: {
  competitionId: string;
  ticketId: string;
  attachment: TicketAttachment;
  onClose: () => void;
}) {
  const { url, failed } = useAttachmentImage(competitionId, ticketId, attachment.id);

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="max-w-[56rem]">
        <DialogTitle className="truncate text-sm font-medium">
          {attachment.filename}
          <span className="ml-2 font-normal text-muted-foreground">
            {formatSize(attachment.size_bytes)}
          </span>
        </DialogTitle>
        <div className="flex max-h-[70vh] items-center justify-center overflow-auto rounded-md bg-muted/40">
          {failed ? (
            <p className="p-8 text-sm text-muted-foreground">
              This image could not be loaded.
            </p>
          ) : url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={url}
              alt={attachment.filename}
              className="max-h-[70vh] w-auto object-contain"
            />
          ) : (
            <div className="h-64 w-full animate-pulse bg-muted" />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function TicketAttachments({
  competitionId,
  ticketId,
  attachments,
  /** The uploader may remove their own; staff may remove any (moderation). */
  canDelete,
}: {
  competitionId: string;
  ticketId: string;
  attachments: TicketAttachment[];
  canDelete: (attachment: TicketAttachment) => boolean;
}) {
  const [viewing, setViewing] = useState<TicketAttachment | null>(null);
  const remove = useDeleteTicketAttachment(competitionId, ticketId);
  const confirm = useConfirm();

  if (attachments.length === 0) return null;

  return (
    <>
      <ul className="mt-2 flex flex-wrap gap-2">
        {attachments.map((attachment) => (
          <li key={attachment.id} className="grid justify-items-center gap-0.5">
            <Thumbnail
              competitionId={competitionId}
              ticketId={ticketId}
              attachment={attachment}
              onOpen={() => setViewing(attachment)}
            />
            {canDelete(attachment) && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-5 px-1.5 text-[10px] text-destructive"
                disabled={remove.isPending}
                onClick={async () => {
                  if (
                    await confirm({
                      title: "Remove attachment?",
                      description: `"${attachment.filename}" will be deleted from this ticket.`,
                      confirmLabel: "Remove",
                      destructive: true,
                    })
                  ) {
                    remove.mutate(attachment.id);
                  }
                }}
              >
                Remove
              </Button>
            )}
          </li>
        ))}
      </ul>

      {viewing && (
        <Lightbox
          competitionId={competitionId}
          ticketId={ticketId}
          attachment={viewing}
          onClose={() => setViewing(null)}
        />
      )}
    </>
  );
}
