"use client";

import { EditorContent, useEditor } from "@tiptap/react";
import * as React from "react";
import { useEffect } from "react";

import { richTextExtensions } from "@/components/ui/rich-text-extensions";
import type { RichTextDoc } from "@/lib/types";
import { cn } from "@/lib/utils";

// Read-only renderer for stored ProseMirror docs (#197): a non-editable TipTap
// instance, so a doc renders as a React tree under the SAME schema the editor
// wrote it with — never innerHTML, and anything outside the schema is dropped
// rather than interpreted. That property is what lets admin-authored rich text
// (sign-in notice, rules, custom pages #198) appear on public pages without a
// sanitizer pass. lib/rich-text.ts's richTextToPlain stays for text-only uses
// (emptiness checks, previews in tables).

/** Renders nothing if its subtree throws.
 *
 * The shape guard below is only doc-deep, and a stored document is effectively
 * untrusted input: it may predate a schema change, have been restored from a
 * backup (which bypasses the write-time validators), or been hand-edited. Some
 * malformed shapes throw *inside* TipTap rather than degrading — a link mark
 * whose `href` is a number reaches `uri.replace(…)` and raises a TypeError, for
 * example. Without a boundary that takes down whichever page embeds this, and
 * the sign-in notice embeds it on `/login`, which is the one page an operator
 * needs in order to fix anything (ADR-0034).
 *
 * A boundary must be an *ancestor* of the throwing component, which is why the
 * editor lives in a separate inner component below rather than in this file's
 * exported one.
 */
class RichTextBoundary extends React.Component<
  { children: React.ReactNode; resetKey: string },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidUpdate(prev: { resetKey: string }) {
    // A new document deserves a fresh attempt — otherwise one bad page would
    // leave the component permanently blank for every later doc it renders.
    if (prev.resetKey !== this.props.resetKey && this.state.failed) {
      this.setState({ failed: false });
    }
  }

  componentDidCatch(error: unknown) {
    // Loud in the console, silent on the page: a reader can do nothing with a
    // stack trace, but whoever has to fix the row needs to know it happened.
    console.error("RichTextView: refusing to render a malformed document", error);
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

function RichTextEditorView({
  doc,
  className,
}: {
  doc: RichTextDoc;
  className?: string;
}) {
  const editor = useEditor(
    {
      extensions: richTextExtensions(),
      editable: false,
      // Avoid an SSR/CSR hydration mismatch in the App Router.
      immediatelyRender: false,
      content: doc,
    },
    // Recreate when the doc changes: view surfaces swap docs rarely (settings
    // refetch, admin preview), so a rebuild is simpler and safer than diffing
    // setContent against a possibly-stale instance.
    [JSON.stringify(doc)],
  );

  // Tear down on unmount to avoid leaking the editor instance across pages.
  useEffect(() => () => editor?.destroy(), [editor]);

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
  // garbage degrades to rendering nothing, same as null. The boundary above
  // covers the malformed shapes this check can't see without walking the tree.
  const doc =
    value && value.type === "doc" && Array.isArray(value.content) ? value : null;

  if (!doc) return null;
  return (
    <RichTextBoundary resetKey={JSON.stringify(doc)}>
      <RichTextEditorView doc={doc} className={className} />
    </RichTextBoundary>
  );
}
