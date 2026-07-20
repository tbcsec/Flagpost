import type { RichTextDoc } from "@/lib/types";

// Challenge descriptions are stored as TipTap/ProseMirror JSON docs (§13.1).
// A full renderer is the editor's job; for read-only surfaces (the challenge
// detail dialog) we just flatten the doc to paragraphs of plain text, which is
// enough to show the prompt without pulling the editor into a view context.
export function richTextToPlain(doc: RichTextDoc | null | undefined): string {
  if (!doc || typeof doc !== "object") return "";
  const out: string[] = [];
  const walk = (node: unknown) => {
    if (!node || typeof node !== "object") return;
    const n = node as { type?: string; text?: string; content?: unknown[] };
    if (typeof n.text === "string") out.push(n.text);
    if (Array.isArray(n.content)) {
      n.content.forEach(walk);
      // Break blocks so paragraphs don't run together.
      if (n.type === "paragraph" || n.type === "heading") out.push("\n");
    }
  };
  walk(doc);
  return out.join("").trim();
}
