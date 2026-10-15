import { describe, expect, it } from "vitest";

import {
  shouldCheckProgrammingProblems,
  visibleCompNav,
  type NavViewer,
} from "@/components/app/nav-visibility";

const NAV = [
  { key: "challenges" },
  { key: "analytics", manage: true, module: "analytics" },
  { key: "instances", module: "instances", permission: "instance_view" },
  { key: "judging", module: "judge", permission: "judging_view" },
];

const viewer = (grants: string[], over: Partial<NavViewer> = {}): NavViewer => ({
  ready: true,
  inLobby: false,
  canManageActiveCompetition: grants.length > 0,
  has: (p) => grants.includes(p),
  ...over,
});

const staff = viewer(["judging_view", "instance_view"]);
const competitor = viewer([]);
const keys = (items: { key: string }[]) => items.map((i) => i.key);

describe("the Judging sidebar entry", () => {
  it("shows for staff once the competition has a programming problem", () => {
    expect(keys(visibleCompNav(NAV, staff, ["judge", "analytics", "instances"], true))).toContain(
      "judging",
    );
  });

  it("stays hidden with no programming problem, or until that's known", () => {
    expect(keys(visibleCompNav(NAV, staff, ["judge"], false))).not.toContain("judging");
    expect(keys(visibleCompNav(NAV, staff, ["judge"], undefined))).not.toContain("judging");
  });

  it("is never shown to competitors, nor asked about for them", () => {
    expect(keys(visibleCompNav(NAV, competitor, ["judge"], true))).not.toContain("judging");
    expect(shouldCheckProgrammingProblems(competitor, ["judge"])).toBe(false);
  });

  it("is only asked about for staff with the judge on, outside the lobby", () => {
    expect(shouldCheckProgrammingProblems(staff, ["judge"])).toBe(true);
    expect(shouldCheckProgrammingProblems(staff, ["analytics"])).toBe(false);
    expect(shouldCheckProgrammingProblems(staff, undefined)).toBe(false);
    expect(shouldCheckProgrammingProblems({ ...staff, inLobby: true }, ["judge"])).toBe(false);
    expect(shouldCheckProgrammingProblems({ ...staff, ready: false }, ["judge"])).toBe(false);
  });
});

describe("the other sidebar rules", () => {
  it("keeps module entries while modules load, and drops disabled ones", () => {
    expect(keys(visibleCompNav(NAV, staff, undefined, true))).toEqual([
      "challenges",
      "analytics",
      "instances",
      "judging",
    ]);
    expect(keys(visibleCompNav(NAV, staff, ["judge"], true))).toEqual(["challenges", "judging"]);
  });

  it("hides staff entries from competitors", () => {
    expect(keys(visibleCompNav(NAV, competitor, undefined, undefined))).toEqual(["challenges"]);
  });
});
