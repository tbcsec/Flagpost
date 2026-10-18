import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { hasModuleIcon, ModuleIcon } from "@/components/app/module-icons";
import en from "../../../messages/en.json";

// Every module the UI writes copy for has a glyph of its own (#502), and an
// unknown one still renders the generic glyph.

describe("ModuleIcon", () => {
  it("has a glyph for every module in the catalog", () => {
    const missing = Object.keys(en.moduleCatalog).filter((id) => !hasModuleIcon(id));
    expect(missing).toEqual([]);
  });

  it("renders a decorative svg, falling back for an unknown module", () => {
    const { container } = render(<ModuleIcon name="no-such-module" />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg?.childElementCount).toBeGreaterThan(0);
  });

  it("draws the sidebar's glyphs exactly as before they moved here", () => {
    // Pinned so an edit to a shared glyph is a deliberate one: these were the
    // sidebar's inline icons before #502 moved them into this catalog.
    const sidebar = [
      "dashboard", "scoring", "teams", "tickets", "analytics", "automations", "feedback",
      "ai", "judge", "instances", "settings", "lobby", "admin",
    ];
    const markup = Object.fromEntries(
      sidebar.map((name) => [name, render(<ModuleIcon name={name} />).container.innerHTML]),
    );
    expect(markup).toMatchSnapshot();
  });
});
