import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { HelpMenu } from "@/components/app/help-menu";

// The help menu lists exactly the guides the viewer's role can use — showing a
// competitor an Admin guide (or hiding the Judge guide from staff) would make
// the docs lie about the product. Gate logic mirrors the shell's access flags.

const access = {
  ready: true,
  has: () => false,
  isAdmin: false,
  canManageActiveCompetition: false,
  canViewAnalytics: false,
  inLobby: false,
};

vi.mock("@/lib/hooks/use-permissions", () => ({
  useAccess: () => access,
}));

function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: "User guides" }));
}

describe("HelpMenu role gating", () => {
  it("shows only the Competitor guide to a competitor", () => {
    access.isAdmin = false;
    access.canManageActiveCompetition = false;
    renderWithIntl(<HelpMenu />);
    openMenu();
    expect(screen.getByRole("link", { name: /Competitor guide/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Judge guide/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /Admin guide/ })).toBeNull();
  });

  it("adds the Judge guide for competition staff", () => {
    access.isAdmin = false;
    access.canManageActiveCompetition = true;
    renderWithIntl(<HelpMenu />);
    openMenu();
    expect(screen.getByRole("link", { name: /Competitor guide/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Judge guide/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Admin guide/ })).toBeNull();
  });

  it("shows all three guides to an administrator", () => {
    access.isAdmin = true;
    access.canManageActiveCompetition = true;
    renderWithIntl(<HelpMenu />);
    openMenu();
    const links = screen.getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual([
      "/guides/flagpost-competitor-guide.pdf",
      "/guides/flagpost-judge-guide.pdf",
      "/guides/flagpost-admin-guide.pdf",
    ]);
  });
});
