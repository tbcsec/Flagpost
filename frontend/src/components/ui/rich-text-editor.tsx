"use client";

import { EditorContent, useEditor, useEditorState } from "@tiptap/react";
import { useTranslations } from "next-intl";
import { useEffect } from "react";

import { ToolbarButton } from "@/components/ui/editor-toolbar-button";
import { richTextExtensions } from "@/components/ui/rich-text-extensions";
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
  const t = useTranslations("common.editor");
  const editor = useEditor({
    extensions: richTextExtensions(),
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
      // Selected purely so a cursor move into/out of an ordered list (typed
      // via "1. " — there's no toolbar button) still triggers a re-render for
      // the alignment gating below.
      orderedList: !!e?.isActive("orderedList"),
      heading2: !!e?.isActive("heading", { level: 2 }),
      // TextAlign stores "left" implicitly, so isActive matches it by default.
      alignLeft: !!e?.isActive({ textAlign: "left" }),
      alignCenter: !!e?.isActive({ textAlign: "center" }),
      alignRight: !!e?.isActive({ textAlign: "right" }),
    }),
  });

  if (!editor) return null;

  // Alignment only exists on free-standing paragraphs/headings: inside a list
  // the marker wouldn't travel with centered text (half-aligned mess) and a
  // code block ignores the attribute entirely — grey the buttons out rather
  // than let them silently no-op or half-apply (#197 follow-up). Computed
  // from the live editor, not the useEditorState snapshot: the snapshot lags
  // until the first transaction, which would wrongly disable the buttons on a
  // freshly-mounted editor. The selector's flags still make selection moves
  // re-render this component, so this stays current.
  const alignable =
    !editor.isActive("codeBlock") &&
    !editor.isActive("bulletList") &&
    !editor.isActive("orderedList");

  return (
    <div>
      <div className="flex flex-wrap gap-1 rounded-t-md border border-input bg-muted/40 p-1">
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
          // Entering a list strips any alignment the paragraphs carried, so a
          // previously-centered line can't smuggle the half-aligned state the
          // disabled buttons exist to prevent.
          onClick={() =>
            editor.chain().focus().toggleBulletList().unsetTextAlign().run()
          }
        />
        <ToolbarButton
          label={t("heading")}
          active={active?.heading2 ?? false}
          onClick={() =>
            editor.chain().focus().toggleHeading({ level: 2 }).run()
          }
        />
        <span aria-hidden className="mx-1 w-px self-stretch bg-border" />
        <ToolbarButton
          label={t("alignLeft")}
          active={(active?.alignLeft ?? false) && alignable}
          disabled={!alignable}
          title={alignable ? undefined : t("alignHint")}
          onClick={() => editor.chain().focus().setTextAlign("left").run()}
        />
        <ToolbarButton
          label={t("alignCenter")}
          active={(active?.alignCenter ?? false) && alignable}
          disabled={!alignable}
          title={alignable ? undefined : t("alignHint")}
          onClick={() => editor.chain().focus().setTextAlign("center").run()}
        />
        <ToolbarButton
          label={t("alignRight")}
          active={(active?.alignRight ?? false) && alignable}
          disabled={!alignable}
          title={alignable ? undefined : t("alignHint")}
          onClick={() => editor.chain().focus().setTextAlign("right").run()}
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
