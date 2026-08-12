import TextAlign from "@tiptap/extension-text-align";
import StarterKit from "@tiptap/starter-kit";

// Single source of the rich-text schema: the editor (RichTextEditor) and the
// read-only view (RichTextView) must agree on extensions, or an attribute
// authored in one is silently dropped by the other. CollabNote deliberately
// stays separate — its schema is coupled to the CRDT (ADR-0014).
//
// TextAlign (#197) covers block nodes only; inline content aligns with its
// block. "left" is the default and is stored implicitly (no attr).
export function richTextExtensions() {
  return [
    StarterKit,
    TextAlign.configure({ types: ["heading", "paragraph"] }),
  ];
}
