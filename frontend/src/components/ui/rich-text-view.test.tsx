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

// --- the security property the rendering path is built on (ADR-0034) ---------
//
// Admin-authored rich text (the sign-in notice #197, custom pages #198) is
// rendered without a sanitiser pass, on the argument that a stored document
// becomes a React tree under ProseMirror's schema rather than markup. The one
// place that argument could still leak script is a **link href**: StarterKit
// bundles the Link mark, so a hostile `javascript:` URL in stored JSON would
// otherwise become a clickable script. TipTap neutralises it — but that is a
// *dependency default*, not something this codebase states, so it is pinned
// here rather than assumed. If a TipTap upgrade ever relaxes it, this fails
// instead of quietly turning `manage_pages` into session theft (the production
// CSP is `script-src 'self' 'unsafe-inline'`, so an injected script executes).

function linkDoc(href: string) {
  return {
    type: "doc",
    content: [
      {
        type: "paragraph",
        content: [
          { type: "text", text: "click me", marks: [{ type: "link", attrs: { href } }] },
        ],
      },
    ],
  };
}

describe("RichTextView link hrefs", () => {
  it.each([
    ["javascript:alert(1)"],
    ["JaVaScRiPt:alert(1)"], // case is not a bypass
    ["  javascript:alert(1)"], // nor is leading whitespace
    ["data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=="],
    ["vbscript:msgbox(1)"],
  ])("neutralises the hostile scheme %s", async (href) => {
    const { container } = render(<RichTextView value={linkDoc(href) as never} />);
    await waitFor(() =>
      expect(container.querySelector(".ProseMirror")).not.toBeNull(),
    );
    const rendered = container.querySelector("a")?.getAttribute("href") ?? "";
    expect(rendered).not.toMatch(/javascript:/i);
    expect(rendered).not.toMatch(/vbscript:/i);
    expect(rendered).not.toMatch(/^data:/i);
  });

  it("still renders an ordinary https link", async () => {
    const { container } = render(
      <RichTextView value={linkDoc("https://ok.example.com/safe") as never} />,
    );
    await waitFor(() =>
      expect(container.querySelector(".ProseMirror")).not.toBeNull(),
    );
    expect(container.querySelector("a")?.getAttribute("href")).toBe(
      "https://ok.example.com/safe",
    );
  });
});

describe("RichTextView malformed documents", () => {
  // The component's contract is that garbage degrades to rendering nothing. The
  // shape guard is only doc-deep, so shapes that throw *inside* TipTap are
  // caught by the boundary — without it, one bad stored row takes down whatever
  // page embeds this, including /login via the sign-in notice.
  it("renders nothing instead of throwing on a non-string link href", () => {
    const doc = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", text: "x", marks: [{ type: "link", attrs: { href: 1234 } }] },
          ],
        },
      ],
    };
    expect(() => render(<RichTextView value={doc as never} />)).not.toThrow();
  });

  it("renders nothing instead of throwing on an unknown node type", () => {
    const doc = {
      type: "doc",
      content: [{ type: "definitely-not-a-node", attrs: {} }],
    };
    expect(() => render(<RichTextView value={doc as never} />)).not.toThrow();
  });
});
