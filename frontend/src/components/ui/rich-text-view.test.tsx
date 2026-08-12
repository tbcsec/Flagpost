import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RichTextView } from "@/components/ui/rich-text-view";

// The read-only renderer must reproduce what the editor authored — marks AND
// the TextAlign attribute (#197) — and must render nothing at all for the
// null/empty state so callers can gate layout on it.

const DOC = {
  type: "doc",
  content: [
    {
      type: "paragraph",
      attrs: { textAlign: "center" },
      content: [
        { type: "text", text: "Use your " },
        {
          type: "text",
          text: "university",
          marks: [{ type: "bold" }],
        },
        { type: "text", text: " account." },
      ],
    },
  ],
};

describe("RichTextView", () => {
  it("renders marks and alignment from a stored doc", async () => {
    const { container } = render(<RichTextView value={DOC} />);
    // immediatelyRender: false → the editor mounts in an effect.
    await waitFor(() => {
      expect(screen.getByText("university")).toBeInTheDocument();
    });
    expect(screen.getByText("university").tagName).toBe("STRONG");
    const p = container.querySelector("p");
    expect(p?.getAttribute("style")).toContain("text-align: center");
  });

  it("is not editable", async () => {
    const { container } = render(<RichTextView value={DOC} />);
    await waitFor(() => {
      expect(container.querySelector(".ProseMirror")).not.toBeNull();
    });
    expect(
      container.querySelector('[contenteditable="true"]'),
    ).toBeNull();
  });

  it("renders nothing for a null doc", () => {
    const { container } = render(<RichTextView value={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("degrades to nothing for a shapeless value instead of throwing", () => {
    // A row restored from an old backup or hand-edited must never crash the
    // login page: anything that isn't doc-shaped renders like null.
    for (const garbage of [{}, { foo: 1 }, { type: "paragraph" }]) {
      const { container, unmount } = render(<RichTextView value={garbage} />);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });
});
