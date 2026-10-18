import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CompetitionSwitcher } from "@/components/app/competition-switcher";
import { renderWithIntl } from "@/test/intl";

// The switcher (#478): a competitor's own competitions apart from public ones
// to join, a Join link to the lobby, and a default selection that prefers a
// joined competition once permissions are in.

const setActiveCompetition = vi.fn();
let activeId: string | null = null;
type Access = {
  ready: boolean;
  failed: boolean;
  seesEveryCompetition: boolean;
  isMemberOf: (id: string) => boolean;
};
let access: Access;

vi.mock("@/lib/hooks/use-competitions", () => ({
  useCompetitions: () => ({
    data: [
      { id: "a", name: "Autumn CTF", archived_at: null },
      { id: "b", name: "Spring CTF", archived_at: null },
      { id: "old", name: "Old CTF", archived_at: "2026-01-01T00:00:00Z" },
    ],
  }),
}));
vi.mock("@/lib/hooks/use-permissions", () => ({ useAccess: () => access }));
vi.mock("@/stores/auth", () => ({
  useAuthStore: (
    select: (s: { activeCompetitionId: string | null; setActiveCompetition: typeof setActiveCompetition }) => unknown,
  ) => select({ activeCompetitionId: activeId, setActiveCompetition }),
}));

const competitor = (): Access => ({
  ready: true,
  failed: false,
  seesEveryCompetition: false,
  isMemberOf: (id) => id === "b",
});

beforeEach(() => {
  setActiveCompetition.mockReset();
  activeId = "b";
  access = competitor();
});

describe("CompetitionSwitcher", () => {
  it("groups a competitor's competitions apart from the ones open to join", () => {
    renderWithIntl(<CompetitionSwitcher visible />);
    const joined = screen.getByRole("group", { name: "Your competitions" });
    const open = screen.getByRole("group", { name: "Open to join" });
    expect(joined).toHaveTextContent("Spring CTF");
    expect(open).toHaveTextContent("Autumn CTF");
    expect(screen.queryByText("Old CTF")).toBeNull();
    expect(screen.getByRole("link", { name: "Join a competition" })).toHaveAttribute("href", "/lobby");
    fireEvent.change(screen.getByRole("combobox", { name: "Competition" }), {
      target: { value: "a" },
    });
    expect(setActiveCompetition).toHaveBeenLastCalledWith("a");
  });

  it("keeps one plain list and no Join link for someone in every competition", () => {
    access = { ...competitor(), seesEveryCompetition: true, isMemberOf: () => true };
    renderWithIntl(<CompetitionSwitcher visible />);
    expect(screen.queryByRole("group")).toBeNull();
    expect(screen.getAllByRole("option")).toHaveLength(2);
    expect(screen.queryByRole("link", { name: "Join a competition" })).toBeNull();
  });

  it("waits for permissions, then defaults to a joined competition", () => {
    activeId = null;
    access = { ...competitor(), ready: false };
    const { rerender } = renderWithIntl(<CompetitionSwitcher visible />);
    expect(setActiveCompetition).not.toHaveBeenCalled();
    access = competitor();
    rerender(<CompetitionSwitcher visible />);
    expect(setActiveCompetition).toHaveBeenCalledWith("b");
  });

  it("still picks one if permissions fail to load", () => {
    activeId = null;
    access = { ...competitor(), ready: false, failed: true, isMemberOf: () => false };
    renderWithIntl(<CompetitionSwitcher visible />);
    expect(setActiveCompetition).toHaveBeenCalledWith("a");
  });

  it("selects even where it isn't shown", () => {
    activeId = null;
    const { container } = renderWithIntl(<CompetitionSwitcher visible={false} />);
    expect(container).toBeEmptyDOMElement();
    expect(setActiveCompetition).toHaveBeenCalledWith("b");
  });
});
