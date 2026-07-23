"use client";

// Collaborative rich-text note (ARCHITECTURE.md §4.2). A TipTap editor whose
// document is a Y.js CRDT synced live over the note room (ADR-0014) — used for a
// team's per-challenge scratchpad and staff internal ticket notes. Prose only;
// simple fields stay plain form submits (§4.2).

import Collaboration from "@tiptap/extension-collaboration";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import * as React from "react";
import * as Y from "yjs";

import { Button } from "@/components/ui/button";
import { bindCollabDoc } from "@/lib/collab";
import { cn } from "@/lib/utils";
import type { RoomSocketStatus } from "@/lib/ws";

export function CollabNote({ docKey }: { docKey: string }) {
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
        // history must be off or the two fight over the same keystrokes.
        StarterKit.configure({ history: false }),
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

  if (!editor) return null;

  const ToolbarButton = ({
    active,
    onClick,
    label,
  }: {
    active: boolean;
    onClick: () => void;
    label: string;
  }) => (
    <Button
      type="button"
      variant={active ? "secondary" : "ghost"}
      size="sm"
      onClick={onClick}
      className={cn("h-7 px-2 text-xs", active && "font-semibold")}
    >
      {label}
    </Button>
  );

  return (
    <div>
      <div className="flex flex-wrap items-center gap-1 rounded-t-md border border-input bg-muted/40 p-1">
        <ToolbarButton
          label="B"
          active={editor.isActive("bold")}
          onClick={() => editor.chain().focus().toggleBold().run()}
        />
        <ToolbarButton
          label="I"
          active={editor.isActive("italic")}
          onClick={() => editor.chain().focus().toggleItalic().run()}
        />
        <ToolbarButton
          label="Code"
          active={editor.isActive("codeBlock")}
          onClick={() => editor.chain().focus().toggleCodeBlock().run()}
        />
        <ToolbarButton
          label="• List"
          active={editor.isActive("bulletList")}
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
  const label = status === "open" ? "Live" : status === "connecting" ? "Connecting…" : "Reconnecting…";
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
