"use client";

import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
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
      <div className="flex flex-wrap gap-1 rounded-t-md border border-input bg-muted/40 p-1">
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
        <ToolbarButton
          label="H2"
          active={editor.isActive("heading", { level: 2 })}
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
