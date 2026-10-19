import { describe, expect, it } from "vitest";

import {
  isCompetitionScopedPath,
  shouldShowJoinPanel,
  switcherGroups,
  shouldCheckModulesInUse,
  shouldCheckProgrammingProblems,
  shouldRedirectToLobby,
  visibleCompNav,
  type NavViewer,
} from "@/components/app/nav-visibility";

const NAV = [
  { key: "challenges" },
  { key: "analytics", manage: true, module: "analytics" },
  { key: "instances", module: "instances", permission: "instance_view", inUse: "instances" },
  { key: "aiTranscripts", module: "ai", permission: "ai_view_transcripts", inUse: "ai" },
  { key: "judging", module: "judge", permission: "judging_view", inUse: "judge" },
];
const ALL_ON = ["judge", "analytics", "instances", "ai"];
const EVERYTHING = { judge: true, ai: true, instances: true };

const viewer = (grants: string[], over: Partial<NavViewer> = {}): NavViewer => ({
  ready: true,
  inLobby: false,
  canManageActiveCompetition: grants.length > 0,
  has: (p) => grants.includes(p),
  ...over,
});

const staff = viewer(["judging_view", "instance_view", "ai_view_transcripts"]);
const competitor = viewer([]);
const keys = (items: { key: string }[]) => items.map((i) => i.key);

describe("the Judging sidebar entry", () => {
  it("shows for staff once the competition has a programming problem", () => {
    expect(keys(visibleCompNav(NAV, staff, ALL_ON, EVERYTHING))).toContain("judging");
  });

  it("stays hidden with no programming problem, or until that's known", () => {
    expect(keys(visibleCompNav(NAV, staff, ["judge"], { judge: false }))).not.toContain("judging");
    expect(keys(visibleCompNav(NAV, staff, ["judge"], {}))).not.toContain("judging");
  });

  it("is never shown to competitors, nor asked about for them", () => {
    expect(keys(visibleCompNav(NAV, competitor, ["judge"], EVERYTHING))).not.toContain("judging");
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

describe("the AI transcripts and Instances entries (#511)", () => {
  it("show only once the module is of use here, and stay hidden until known", () => {
    expect(keys(visibleCompNav(NAV, staff, ALL_ON, { ai: true, instances: false }))).toEqual([
      "challenges",
      "analytics",
      "aiTranscripts",
    ]);
    expect(keys(visibleCompNav(NAV, staff, ALL_ON, { instances: true }))).toEqual([
      "challenges",
      "analytics",
      "instances",
    ]);
    expect(keys(visibleCompNav(NAV, staff, ALL_ON, {}))).toEqual(["challenges", "analytics"]);
  });

  it("are only asked about for someone who could open one, with that module on", () => {
    expect(shouldCheckModulesInUse(staff, ALL_ON)).toBe(true);
    expect(shouldCheckModulesInUse(viewer(["instance_view"]), ["ai"])).toBe(false);
    expect(shouldCheckModulesInUse(viewer(["instance_view"]), ["instances"])).toBe(true);
    expect(shouldCheckModulesInUse(viewer(["ai_view_transcripts"]), ["ai"])).toBe(true);
    expect(shouldCheckModulesInUse(competitor, ALL_ON)).toBe(false);
    expect(shouldCheckModulesInUse(staff, undefined)).toBe(false);
    expect(shouldCheckModulesInUse({ ...staff, inLobby: true }, ALL_ON)).toBe(false);
    expect(shouldCheckModulesInUse({ ...staff, ready: false }, ALL_ON)).toBe(false);
  });
});

describe("the other sidebar rules", () => {
  it("keeps module entries while modules load, and drops disabled ones", () => {
    expect(keys(visibleCompNav(NAV, staff, undefined, EVERYTHING))).toEqual([
      "challenges",
      "analytics",
      "instances",
      "aiTranscripts",
      "judging",
    ]);
    expect(keys(visibleCompNav(NAV, staff, ["judge"], EVERYTHING))).toEqual(["challenges", "judging"]);
  });

  it("hides staff entries from competitors", () => {
    expect(keys(visibleCompNav(NAV, competitor, undefined, {}))).toEqual(["challenges"]);
  });
});

describe("the lobby redirect", () => {
  const go = (pathname: string, isAdmin = false, showLobby = true) =>
    shouldRedirectToLobby({ showLobby, pathname, isAdmin });

  it("sends a lobby-state viewer off competition pages", () => {
    expect(go("/")).toBe(true);
    expect(go("/challenges")).toBe(true);
  });

  it("leaves the lobby, the profile, and anyone not in the lobby alone", () => {
    expect(go("/lobby")).toBe(false);
    expect(go("/profile")).toBe(false);
    expect(go("/challenges", false, false)).toBe(false);
  });

  it("lets a narrow global delegate stay on the Admin pages (#477)", () => {
    expect(go("/admin/events", true)).toBe(false);
    // …but not elsewhere, and not someone who can't open Admin at all.
    expect(go("/challenges", true)).toBe(true);
    expect(go("/admin/events", false)).toBe(true);
  });
});

describe("a competition the viewer hasn't joined (#478)", () => {
  const member = { ready: true, inLobby: false, memberOfActive: true, hasActiveCompetition: true };

  it("treats everything but Admin, the lobby and the profile as competition pages", () => {
    for (const path of ["/", "/challenges", "/scoreboard", "/support", "/settings", "/administrators"]) {
      expect(isCompetitionScopedPath(path), path).toBe(true);
    }
    for (const path of ["/admin", "/admin/users", "/lobby", "/profile"]) {
      expect(isCompetitionScopedPath(path), path).toBe(false);
    }
  });

  it("shows the join panel on competition pages of an unjoined competition", () => {
    const visitor = { ...member, memberOfActive: false };
    expect(shouldShowJoinPanel({ ...visitor, pathname: "/challenges" })).toBe(true);
    expect(shouldShowJoinPanel({ ...visitor, pathname: "/profile" })).toBe(false);
    expect(shouldShowJoinPanel({ ...visitor, pathname: "/admin/events" })).toBe(false);
  });

  it("never for a member, the lobby, before permissions load, or with nothing active", () => {
    expect(shouldShowJoinPanel({ ...member, pathname: "/" })).toBe(false);
    const visitor = { ...member, memberOfActive: false, pathname: "/" };
    expect(shouldShowJoinPanel({ ...visitor, inLobby: true })).toBe(false);
    expect(shouldShowJoinPanel({ ...visitor, ready: false })).toBe(false);
    expect(shouldShowJoinPanel({ ...visitor, hasActiveCompetition: false })).toBe(false);
  });

  it("groups the switcher into joined and open-to-join for a competitor", () => {
    const comps = [{ id: "a" }, { id: "b" }, { id: "c" }];
    const viewer = { ready: true, seesEveryCompetition: false, isMemberOf: (id: string) => id === "b" };
    expect(switcherGroups(comps, viewer)).toEqual({
      joined: [{ id: "b" }],
      joinable: [{ id: "a" }, { id: "c" }],
    });
  });

  it("keeps one flat list when there's nothing to tell apart", () => {
    const comps = [{ id: "a" }, { id: "b" }];
    const competitor = { ready: true, seesEveryCompetition: false };
    expect(switcherGroups(comps, { ...competitor, isMemberOf: () => true })).toBeNull();
    expect(switcherGroups(comps, { ...competitor, isMemberOf: () => false })).toBeNull();
    // An Administrator is in every competition; and nothing before permissions
    // load — even for a membership that would otherwise split the list.
    const onlyA = (id: string) => id === "a";
    expect(
      switcherGroups(comps, { ready: true, seesEveryCompetition: true, isMemberOf: onlyA }),
    ).toBeNull();
    expect(switcherGroups(comps, { ...competitor, ready: false, isMemberOf: onlyA })).toBeNull();
  });
});
