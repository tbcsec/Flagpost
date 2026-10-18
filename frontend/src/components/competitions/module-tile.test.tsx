import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ModuleTile } from "@/components/competitions/module-tile";
import { renderWithIntl } from "@/test/intl";

// A module as a tile (#502): the UI's own name and description, a switch, and
// the site-setup note for an inert module.

describe("ModuleTile", () => {
  it("shows the UI's copy for a known module and flips its switch", () => {
    const onToggle = vi.fn();
    renderWithIntl(
      <ModuleTile
        module={{ id: "judge", name: "Code Judge", description: "Programming challenges graded…" }}
        enabled={false}
        onToggle={onToggle}
      />,
    );
    const toggle = screen.getByRole("switch", { name: "Code judge" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText(/run against hidden tests and judged automatically/)).toBeInTheDocument();
    expect(screen.queryByText("Programming challenges graded…")).toBeNull();
    fireEvent.click(toggle);
    expect(onToggle).toHaveBeenCalledWith(true);
  });

  it("falls back to the manifest for a module the UI doesn't know", () => {
    renderWithIntl(
      <ModuleTile
        module={{ id: "ctf_radio", name: "CTF Radio", description: "Music while you hack." }}
        enabled
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByRole("switch", { name: "CTF Radio" })).toBeInTheDocument();
    expect(screen.getByText("Music while you hack.")).toBeInTheDocument();
  });

  it("says when an inert module still needs site setup", () => {
    renderWithIntl(
      <ModuleTile module={{ id: "ai", name: "AI", needs_setup: true }} enabled onToggle={vi.fn()} />,
    );
    expect(screen.getByText(/Needs site setup/)).toBeInTheDocument();
  });

  it("marks a required-core module always on, with no switch", () => {
    renderWithIntl(
      <ModuleTile module={{ id: "challenges", name: "Challenges" }} enabled alwaysOn compact />,
    );
    expect(screen.getByText("Always on")).toBeInTheDocument();
    expect(screen.queryByRole("switch")).toBeNull();
    // Compact: the name without the description.
    expect(screen.getByText("Challenges")).toBeInTheDocument();
    expect(screen.queryByText(/flags, categories/)).toBeNull();
  });

  it("holds the switch while a change is in flight", () => {
    renderWithIntl(
      <ModuleTile module={{ id: "feedback", name: "Feedback" }} enabled pending onToggle={vi.fn()} />,
    );
    expect(screen.getByRole("switch", { name: "Feedback" })).toBeDisabled();
  });

  it("keeps the module id and version to hand for support", () => {
    const { container } = renderWithIntl(
      <ModuleTile module={{ id: "reports", name: "Reports", version: "1.2.0" }} enabled onToggle={vi.fn()} />,
    );
    expect(container.firstElementChild).toHaveAttribute("title", "reports · v1.2.0");
  });
});
