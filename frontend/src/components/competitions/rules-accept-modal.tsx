"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { richTextToPlain } from "@/lib/rich-text";
import type { RulesPromptMode } from "@/lib/rules-prompt";
import type { RichTextDoc } from "@/lib/types";

// The rules / code-of-conduct prompt (#57). Two modes (lib/rules-prompt.ts):
// "accept" gates the primary action behind an explicit checkbox — competing
// is impossible until the box is ticked and Accept pressed; "display" is
// informational (owner follow-up) — the same document with a plain Continue.
// Read-only rendering flattens the rich-text doc to paragraphs, the same idiom
// the challenge dialog uses for descriptions.
export function RulesAcceptModal({
  open,
  mode,
  rules,
  title = "Competition rules",
  pending = false,
  dismissable = true,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  mode: Exclude<RulesPromptMode, null>;
  rules: RichTextDoc | null;
  title?: string;
  /** Accept request in flight — the confirm button shows progress. */
  pending?: boolean;
  /** False for the in-app re-acceptance gate: no escape without accepting. */
  dismissable?: boolean;
  /** Accept (mode "accept") or Continue (mode "display"). */
  onConfirm: () => void;
  onCancel?: () => void;
}) {
  const [agreed, setAgreed] = useState(false);
  // A reopened prompt (or a different competition's) starts unchecked —
  // adjust during render on the open transition, per the React idiom.
  const [prevOpen, setPrevOpen] = useState(open);
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) setAgreed(false);
  }

  const mustAccept = mode === "accept";
  const text = richTextToPlain(rules);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && dismissable) onCancel?.();
      }}
    >
      <DialogContent
        onInteractOutside={(e) => {
          if (!dismissable) e.preventDefault();
        }}
        onEscapeKeyDown={(e) => {
          if (!dismissable) e.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {mustAccept
              ? "You must accept these rules before you can compete."
              : "Please review the rules for this competition."}
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-80 overflow-y-auto rounded-md border border-border bg-muted/30 p-4">
          <p className="whitespace-pre-line text-sm leading-relaxed text-foreground">
            {text || "No rules text."}
          </p>
        </div>

        {mustAccept && (
          <label className="flex items-start gap-2.5 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 rounded border-border"
              style={{ accentColor: "hsl(var(--primary))" }}
              checked={agreed}
              onChange={(e) => setAgreed(e.target.checked)}
            />
            <span>I have read and accept these rules.</span>
          </label>
        )}

        <DialogFooter>
          {dismissable && (
            <Button type="button" variant="ghost" onClick={() => onCancel?.()}>
              Cancel
            </Button>
          )}
          <Button
            type="button"
            disabled={(mustAccept && !agreed) || pending}
            onClick={onConfirm}
          >
            {mustAccept ? (pending ? "Accepting…" : "Accept") : "Continue"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
