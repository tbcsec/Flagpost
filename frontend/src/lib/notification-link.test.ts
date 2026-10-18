import { describe, expect, it } from "vitest";

import { competitionToSwitchTo, safeNotificationLink } from "@/lib/notification-link";

describe("safeNotificationLink", () => {
  it("follows only internal, same-origin paths", () => {
    expect(safeNotificationLink("/support?ticket=t1")).toBe("/support?ticket=t1");
    for (const bad of [null, undefined, "", "//evil.example", "javascript:alert(1)", "https://x.example/"]) {
      expect(safeNotificationLink(bad)).toBeNull();
    }
  });
});

describe("competitionToSwitchTo (#508)", () => {
  it("switches to the notification's competition only when it's another one", () => {
    expect(competitionToSwitchTo({ competition_id: "c2" }, "c1")).toBe("c2");
    expect(competitionToSwitchTo({ competition_id: "c1" }, "c1")).toBeNull();
    expect(competitionToSwitchTo({ competition_id: null }, "c1")).toBeNull();
    expect(competitionToSwitchTo({ competition_id: "c2" }, null)).toBe("c2");
  });
});
