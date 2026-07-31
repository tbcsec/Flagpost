"use client";

// Choosing screenshots to attach to a ticket message (issue #80). The files are
// held here until the message they belong to exists — a ticket/reply is posted
// first, then each file is uploaded against the returned message id — so this
// is the "remove before posting" half of the feature; removing an *already
// posted* attachment lives in <TicketAttachments>.
//
// The limits are enforced server-side; the client-side copies exist to fail
// fast with a useful message instead of a round trip that 413s.

import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";

export const MAX_ATTACHMENT_BYTES = 2_621_440; // 2.5 MB — matches the backend
export const MAX_ATTACHMENTS_PER_TICKET = 5;
export const ACCEPTED_IMAGE_TYPES = "image/png,image/jpeg,image/webp";

const ACCEPTED = new Set(["image/png", "image/jpeg", "image/webp"]);

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function ScreenshotPicker({
  files,
  onChange,
  /** Attachments already on this ticket — they share the per-ticket cap. */
  existingCount = 0,
  disabled = false,
}: {
  files: File[];
  onChange: (files: File[]) => void;
  existingCount?: number;
  disabled?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  // Why a file the user picked didn't appear in the list — dropping one in
  // silence just looks broken.
  const [notice, setNotice] = useState<string | null>(null);
  const remaining = MAX_ATTACHMENTS_PER_TICKET - existingCount - files.length;

  function onFilesChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const chosen = Array.from(e.target.files ?? []);
    // Reset immediately so picking the same file twice still fires onChange.
    if (input.current) input.current.value = "";

    const reasons: string[] = [];
    const accepted = chosen.filter((f) => {
      if (!ACCEPTED.has(f.type)) {
        reasons.push(`${f.name} isn't a PNG, JPEG or WebP image`);
        return false;
      }
      if (f.size === 0 || f.size > MAX_ATTACHMENT_BYTES) {
        reasons.push(`${f.name} is larger than ${formatSize(MAX_ATTACHMENT_BYTES)}`);
        return false;
      }
      return true;
    });

    const room = MAX_ATTACHMENTS_PER_TICKET - existingCount - files.length;
    if (accepted.length > room) {
      reasons.push(
        `only ${MAX_ATTACHMENTS_PER_TICKET} images can be attached to a ticket`,
      );
    }
    setNotice(reasons.length > 0 ? `Skipped: ${reasons.join("; ")}.` : null);
    onChange([...files, ...accepted.slice(0, Math.max(room, 0))]);
  }

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={input}
          type="file"
          accept={ACCEPTED_IMAGE_TYPES}
          multiple
          onChange={onFilesChosen}
          disabled={disabled || remaining <= 0}
          aria-label="Attach screenshots"
          className="max-w-full text-sm text-muted-foreground file:mr-3 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-1.5 file:text-sm file:text-secondary-foreground hover:file:bg-secondary/80 disabled:opacity-50"
        />
        <span className="text-xs text-muted-foreground">
          {remaining > 0
            ? `PNG, JPEG or WebP · up to ${formatSize(MAX_ATTACHMENT_BYTES)} each · ${remaining} left`
            : "Attachment limit reached for this ticket"}
        </span>
      </div>

      {files.length > 0 && (
        <ul className="grid gap-1">
          {files.map((file, i) => (
            <li
              key={`${file.name}-${i}`}
              className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/40 px-2 py-1"
            >
              <span className="truncate text-xs">
                {file.name}
                <span className="ml-2 text-muted-foreground">{formatSize(file.size)}</span>
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-6 shrink-0 px-2 text-xs text-destructive"
                onClick={() => {
                  setNotice(null);
                  onChange(files.filter((_, j) => j !== i));
                }}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}

      {notice && (
        <p role="alert" className="text-xs text-destructive">
          {notice}
        </p>
      )}
    </div>
  );
}
