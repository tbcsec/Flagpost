"use client";

// Collaborative rich-text note (ARCHITECTURE.md §4.2). A TipTap editor whose
// document is a Y.js CRDT synced live over the note room (ADR-0014) — used for a
// team's per-challenge scratchpad and staff internal ticket notes. Prose only;
// simple fields stay plain form submits (§4.2).

import Collaboration from "@tiptap/extension-collaboration";
import { EditorContent, useEditor, useEditorState } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useTranslations } from "next-intl";
import * as React from "react";
import * as Y from "yjs";

import { ToolbarButton } from "@/components/ui/editor-toolbar-button";
import { bindCollabDoc } from "@/lib/collab";
import { cn } from "@/lib/utils";
import type { RoomSocketStatus } from "@/lib/ws";

export function CollabNote({ docKey }: { docKey: string }) {
  const t = useTranslations("common.editor");
  // A fresh Y.Doc whenever the note changes — a stale doc must never bleed
  // across resources. `docKey` is a real dependency even though the factory
  // doesn't read it (we want re-creation on change), so the lint is a false
  // positive here.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const ydoc = React.useMemo(() => new Y.Doc(), [docKey]);
  const [status, setStatus] = React.useState<RoomSocketStatus>("connecting");

  React.useEffect(() => {
    const handle = bindCollabDoc(ydoc, docKey, { onStatus: setStatus });
    // Only close the transport on cleanup — do NOT destroy the memoized doc:
    // React StrictMode double-invokes this effect, and the second run rebinds
    // the *same* doc, so destroying it here would bind a dead doc. The doc is
    // small and GC'd once the component (and its editor) unmount for real.
    return () => handle.close();
  }, [ydoc, docKey]);

  const editor = useEditor(
    {
      immediatelyRender: false,
      extensions: [
        // Collaboration owns undo/redo (via the shared doc), so StarterKit's own
        // undo/redo (TipTap 3's rename of `history`) must be off or the two
        // fight over the same keystrokes.
        StarterKit.configure({ undoRedo: false }),
        Collaboration.configure({ document: ydoc }),
      ],
      editorProps: {
        attributes: {
          class:
            "min-h-32 rounded-b-md border border-t-0 border-input bg-background px-3 py-2 text-sm text-foreground focus:outline-none prose-sm max-w-none",
        },
      },
    },
    [ydoc],
  );

  React.useEffect(() => () => editor?.destroy(), [editor]);

  // TipTap 3's useEditor no longer re-renders the host component on editor
  // transactions (v2 did; the compat flag is marked legacy), so toolbar active
  // states must be derived via useEditorState — it re-renders exactly when the
  // selected flags change.
  const active = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: !!e?.isActive("bold"),
      italic: !!e?.isActive("italic"),
      codeBlock: !!e?.isActive("codeBlock"),
      bulletList: !!e?.isActive("bulletList"),
    }),
  });

  if (!editor) return null;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-1 rounded-t-md border border-input bg-muted/40 p-1">
        <ToolbarButton
          label={t("bold")}
          active={active?.bold ?? false}
          onClick={() => editor.chain().focus().toggleBold().run()}
        />
        <ToolbarButton
          label={t("italic")}
          active={active?.italic ?? false}
          onClick={() => editor.chain().focus().toggleItalic().run()}
        />
        <ToolbarButton
          label={t("code")}
          active={active?.codeBlock ?? false}
          onClick={() => editor.chain().focus().toggleCodeBlock().run()}
        />
        <ToolbarButton
          label={t("list")}
          active={active?.bulletList ?? false}
          onClick={() => editor.chain().focus().toggleBulletList().run()}
        />
        <span className="ml-auto pr-1">
          <ConnectionDot status={status} />
        </span>
      </div>
      <EditorContent editor={editor} />
    </div>
  );
}

function ConnectionDot({ status }: { status: RoomSocketStatus }) {
  const t = useTranslations("common.editor");
  const label =
    status === "open" ? t("live") : status === "connecting" ? t("connecting") : t("reconnecting");
  return (
    <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
      <span
        className={cn(
          "inline-block h-1.5 w-1.5 rounded-full",
          status === "open" ? "bg-success" : "bg-muted-foreground/50",
        )}
        aria-hidden
      />
      {label}
    </span>
  );
}
