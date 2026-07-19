"use client";

import { useRef } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  useAttachments,
  useDeleteAttachment,
  useDownloadAttachment,
  useUploadAttachment,
} from "@/lib/hooks/use-attachments";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Attachment manager for the challenge editor. Downloads go through a freshly
// fetched short-lived signed URL (§13.3) — the URL is never rendered into the
// page or stored.
export function AttachmentsSection({
  competitionId,
  challengeId,
}: {
  competitionId: string;
  challengeId: string;
}) {
  const attachments = useAttachments(competitionId, challengeId);
  const upload = useUploadAttachment(competitionId, challengeId);
  const remove = useDeleteAttachment(competitionId, challengeId);
  const download = useDownloadAttachment(competitionId, challengeId);
  const fileInput = useRef<HTMLInputElement>(null);

  function onFileChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    upload.mutate(file, {
      onSettled: () => {
        if (fileInput.current) fileInput.current.value = "";
      },
    });
  }

  return (
    <div className="space-y-3 rounded-md border border-border p-4">
      <Label>Attachments</Label>

      {attachments.data && attachments.data.length > 0 ? (
        <ul className="space-y-2">
          {attachments.data.map((attachment) => (
            <li
              key={attachment.id}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <span className="truncate">
                {attachment.filename}
                <span className="ml-2 text-xs text-muted-foreground">
                  {formatSize(attachment.size_bytes)}
                </span>
              </span>
              <span className="flex shrink-0 gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={download.isPending}
                  onClick={() => download.mutate(attachment.id)}
                >
                  Download
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="text-destructive"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(attachment.id)}
                >
                  Remove
                </Button>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">No files attached.</p>
      )}

      <div className="flex items-center gap-3">
        <input
          ref={fileInput}
          type="file"
          onChange={onFileChosen}
          disabled={upload.isPending}
          className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-1.5 file:text-sm file:text-secondary-foreground hover:file:bg-secondary/80"
        />
        {upload.isPending && (
          <span className="text-sm text-muted-foreground">Uploading…</span>
        )}
      </div>
      {(upload.isError || download.isError || remove.isError) && (
        <p className="text-sm text-destructive">
          {
            (
              (upload.error ?? download.error ?? remove.error) as Error
            ).message
          }
        </p>
      )}
    </div>
  );
}
