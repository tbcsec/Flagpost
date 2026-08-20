import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  DEFAULT_PAGE_ICON,
  PAGE_ICON_NAMES,
  PageIcon,
} from "@/components/app/page-icons";

// Custom-page sidebar glyphs (#198, ADR-0034). The catalog is a closed set of
// *names* rather than admin-supplied markup, so the properties worth pinning are
// that every name renders and that an unknown one degrades instead of blanking
// the sidebar entry.

function iconName(container: HTMLElement): string | null {
  return container.querySelector("svg")?.getAttribute("data-page-icon") ?? null;
}

describe("PageIcon", () => {
  it("renders every name in the catalog", () => {
    expect(PAGE_ICON_NAMES.length).toBeGreaterThan(10);
    for (const name of PAGE_ICON_NAMES) {
      const { container } = render(<PageIcon name={name} />);
      expect(container.querySelector("svg"), name).not.toBeNull();
      expect(iconName(container)).toBe(name);
    }
  });

  // Inherited Object.prototype keys are the case a naive
  // `ICON_PATHS[name] ?? default` lookup gets wrong: the lookup returns an
  // inherited value that isn't nullish, so the fallback never fires and React
  // is handed a non-element. Because this renders in the sidebar on every
  // authenticated route, that would take down the whole shell — including the
  // admin screen needed to undo it — from one stored icon name.
  it.each([
    ["not-a-real-icon"],
    [""],
    [null],
    [undefined],
    ["__proto__"],
    ["constructor"],
    ["toString"],
    ["hasOwnProperty"],
    ["valueOf"],
  ])(
    "falls back to the default glyph for %s",
    (name) => {
      // An older export or a hand-edited row must not blank the entry — the
      // catalog can shrink without stranding data.
      expect(() =>
        render(<PageIcon name={name as string | null} />),
      ).not.toThrow();
      const { container } = render(<PageIcon name={name as string | null} />);
      const svg = container.querySelector("svg");
      expect(svg).not.toBeNull();
      // Real geometry, not an inherited object rendered as a child.
      expect(svg?.querySelector("path")).not.toBeNull();
    },
  );

  it("includes the default glyph in the catalog", () => {
    expect(PAGE_ICON_NAMES).toContain(DEFAULT_PAGE_ICON);
  });

  it("draws in the shell's icon convention so it sits with the built-in nav", () => {
    const { container } = render(<PageIcon name="info" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("viewBox")).toBe("0 0 24 24");
    expect(svg.getAttribute("stroke")).toBe("currentColor");
    expect(svg.getAttribute("stroke-width")).toBe("2");
    expect(svg.getAttribute("fill")).toBe("none");
    // Decorative: the nav link's text already names the page.
    expect(svg.getAttribute("aria-hidden")).toBe("true");
  });

  it("never emits a fill colour, so glyphs follow the theme", () => {
    // The opposite of components/brand/, whose marks carry fixed brand colours.
    for (const name of PAGE_ICON_NAMES) {
      const { container } = render(<PageIcon name={name} />);
      const html = container.innerHTML;
      expect(html, name).not.toMatch(/fill="#/);
    }
  });
});
