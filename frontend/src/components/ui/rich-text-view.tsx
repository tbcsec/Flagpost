"use client";

import { EditorContent, useEditor } from "@tiptap/react";
import { useEffect } from "react";

import { richTextExtensions } from "@/components/ui/rich-text-extensions";
import type { RichTextDoc } from "@/lib/types";
import { cn } from "@/lib/utils";

// Read-only renderer for stored ProseMirror docs (#197): a non-editable TipTap
// instance, so a doc renders as a React tree under the SAME schema the editor
// wrote it with — never innerHTML, and anything outside the schema is dropped
// rather than interpreted. That property is what lets admin-authored rich text
// (sign-in notice, rules) appear on public pages without a sanitizer pass.
// lib/rich-text.ts's richTextToPlain stays for text-only uses (emptiness
// checks, previews in tables).
export function RichTextView({
  value,
  className,
}: {
  value: RichTextDoc | null | undefined;
  className?: string;
}) {
  // Only feed TipTap something doc-shaped: the write path validates this, but
  // a row restored from an old backup or edited by hand mustn't be able to
  // throw inside editor creation and take the page (login!) down with it —
  // garbage degrades to rendering nothing, same as null.
  const doc =
    value && value.type === "doc" && Array.isArray(value.content)
      ? value
      : null;
  const editor = useEditor(
    {
      extensions: richTextExtensions(),
      editable: false,
      // Avoid an SSR/CSR hydration mismatch in the App Router.
      immediatelyRender: false,
      content: doc ?? undefined,
    },
    // Recreate when the doc changes: view surfaces swap docs rarely (settings
    // refetch, admin preview), so a rebuild is simpler and safer than diffing
    // setContent against a possibly-stale instance.
    [JSON.stringify(doc)],
  );

  // Tear down on unmount to avoid leaking the editor instance across pages.
  useEffect(() => () => editor?.destroy(), [editor]);

  if (!doc) return null;
  return (
    <EditorContent
      editor={editor}
      className={cn(
        "prose-sm max-w-none text-sm text-foreground [&_.ProseMirror]:outline-none",
        className,
      )}
    />
  );
}
