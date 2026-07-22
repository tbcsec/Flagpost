import { describe, expect, it } from "vitest";

import { summarizePresence, type PresenceMember } from "@/lib/hooks/use-presence";

const ada: PresenceMember = { id: "u-ada", name: "Ada", role: "participant" };
const judge: PresenceMember = { id: "u-judge", name: "Judge", role: "staff" };
const self: PresenceMember = { id: "me", name: "Me", role: "participant" };

describe("summarizePresence", () => {
  it("excludes the current user from `others` but keeps them in `members`", () => {
    const s = summarizePresence([self, ada, judge], "me");
    expect(s.members).toHaveLength(3);
    expect(s.others.map((m) => m.id)).toEqual(["u-ada", "u-judge"]);
  });

  it("flags a staff member present other than the current user", () => {
    expect(summarizePresence([self, judge], "me").staffPresent).toBe(true);
    expect(summarizePresence([self, ada], "me").staffPresent).toBe(false);
  });

  it("does not count the current user's own staff role as another judge", () => {
    const staffSelf: PresenceMember = { id: "me", name: "Me", role: "staff" };
    expect(summarizePresence([staffSelf, ada], "me").staffPresent).toBe(false);
  });

  it("treats an unknown self id as everyone being 'other'", () => {
    const s = summarizePresence([ada, judge], undefined);
    expect(s.others).toHaveLength(2);
  });
});
