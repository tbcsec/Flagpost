"use client";

import { EditorContent, useEditor, useEditorState } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect } from "react";

import { ToolbarButton } from "@/components/ui/editor-toolbar-button";
import type { RichTextDoc } from "@/lib/types";

// Rich-text primitive (TipTap, §2) emitting a ProseMirror JSON doc — the same
// shape the backend stores. Token-styled toolbar; a fuller toolbar / images
// come with the writeup work in later tiers.
export function RichTextEditor({
  value,
  onChange,
}: {
  value: RichTextDoc;
  onChange: (doc: RichTextDoc) => void;
}) {
  const editor = useEditor({
    extensions: [StarterKit],
    // Avoid an SSR/CSR hydration mismatch in the App Router.
    immediatelyRender: false,
    content: hasContent(value) ? value : undefined,
    onUpdate: ({ editor }) => onChange(editor.getJSON() as RichTextDoc),
    editorProps: {
      attributes: {
        class:
          "min-h-32 rounded-b-md border border-t-0 border-input bg-background px-3 py-2 text-sm text-foreground focus:outline-none prose-sm max-w-none",
      },
    },
  });

  // Tear down on unmount to avoid leaking the editor instance across pages.
  useEffect(() => () => editor?.destroy(), [editor]);

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
      heading2: !!e?.isActive("heading", { level: 2 }),
    }),
  });

  if (!editor) return null;

  return (
    <div>
      <div className="flex flex-wrap gap-1 rounded-t-md border border-input bg-muted/40 p-1">
        <ToolbarButton
          label="B"
          active={active?.bold ?? false}
          onClick={() => editor.chain().focus().toggleBold().run()}
        />
        <ToolbarButton
          label="I"
          active={active?.italic ?? false}
          onClick={() => editor.chain().focus().toggleItalic().run()}
        />
        <ToolbarButton
          label="Code"
          active={active?.codeBlock ?? false}
          onClick={() => editor.chain().focus().toggleCodeBlock().run()}
        />
        <ToolbarButton
          label="• List"
          active={active?.bulletList ?? false}
          onClick={() => editor.chain().focus().toggleBulletList().run()}
        />
        <ToolbarButton
          label="H2"
          active={active?.heading2 ?? false}
          onClick={() =>
            editor.chain().focus().toggleHeading({ level: 2 }).run()
          }
        />
      </div>
      <EditorContent editor={editor} />
    </div>
  );
}

function hasContent(doc: RichTextDoc): boolean {
  const content = (doc as { content?: unknown[] }).content;
  return Array.isArray(content) && content.length > 0;
}
