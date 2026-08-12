import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { RichTextEditor } from "@/components/ui/rich-text-editor";

// TipTap's command chains call .focus(), and ProseMirror's caret positioning
// then walks Range.getClientRects()/getBoundingClientRect() — neither exists
// in jsdom. Without these stubs the geometry lookup surfaces as an *async
// unhandled error* that fails CI even though every assertion passes. The
// tests assert document/toolbar state, never pixels, so empty boxes are fine.
beforeAll(() => {
  const rect = {
    x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0,
    width: 0, height: 0,
    toJSON: () => ({}),
  } as DOMRect;
  Range.prototype.getBoundingClientRect = () => rect;
  Range.prototype.getClientRects = () =>
    Object.assign([], { item: () => null }) as unknown as DOMRectList;
});

// Alignment only exists on free-standing paragraphs/headings (#197 follow-up):
// inside a list the marker wouldn't travel with the text and a code block
// ignores the attribute, so the toolbar must grey the buttons out there
// instead of letting them silently no-op or half-apply.

const PARAGRAPH_DOC = {
  type: "doc",
  content: [
    { type: "paragraph", content: [{ type: "text", text: "hello" }] },
  ],
};

const LIST_DOC = {
  type: "doc",
  content: [
    {
      type: "bulletList",
      content: [
        {
          type: "listItem",
          content: [
            { type: "paragraph", content: [{ type: "text", text: "item" }] },
          ],
        },
      ],
    },
  ],
};

const CENTERED_DOC = {
  type: "doc",
  content: [
    {
      type: "paragraph",
      attrs: { textAlign: "center" },
      content: [{ type: "text", text: "centered" }],
    },
  ],
};

describe("RichTextEditor alignment gating", () => {
  it("enables the alignment buttons on a plain paragraph", async () => {
    render(<RichTextEditor value={PARAGRAPH_DOC} onChange={vi.fn()} />);
    // The toolbar renders disabled until the deferred editor mounts
    // (immediatelyRender: false) and its state propagates — wait it out.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Center" })).toBeEnabled(),
    );
    for (const label of ["Left", "Right"]) {
      expect(screen.getByRole("button", { name: label })).toBeEnabled();
    }
  });

  it("disables the alignment buttons while the cursor is in a list", async () => {
    // The initial selection sits in the first textblock — the list item.
    render(<RichTextEditor value={LIST_DOC} onChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("item")).toBeInTheDocument());
    for (const label of ["Left", "Center", "Right"]) {
      expect(screen.getByRole("button", { name: label })).toBeDisabled();
    }
  });

  it("strips alignment when a paragraph is turned into a list", async () => {
    const onChange = vi.fn();
    render(<RichTextEditor value={CENTERED_DOC} onChange={onChange} />);
    await waitFor(() =>
      expect(screen.getByText("centered")).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "• List" }));

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const doc = onChange.mock.calls.at(-1)![0] as {
      content: Array<{
        type: string;
        content: Array<{
          content: Array<{ attrs?: { textAlign?: string | null } }>;
        }>;
      }>;
    };
    expect(doc.content[0].type).toBe("bulletList");
    const para = doc.content[0].content[0].content[0];
    // "left" is TextAlign's implicit default — anything but "center" proves
    // the stale alignment didn't smuggle into the list.
    expect(para.attrs?.textAlign ?? "left").not.toBe("center");
  });
});
