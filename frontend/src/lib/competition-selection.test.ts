import { describe, expect, it } from "vitest";

import { pickActiveCompetitionId } from "@/lib/competition-selection";

describe("pickActiveCompetitionId", () => {
  const ids = ["a", "b", "c"];

  it("keeps the current selection when it's still visible", () => {
    expect(pickActiveCompetitionId("b", ids)).toBe("b");
  });

  it("defaults to the first competition when nothing is selected", () => {
    expect(pickActiveCompetitionId(null, ids)).toBe("a");
    expect(pickActiveCompetitionId(undefined, ids)).toBe("a");
  });

  it("falls back to the first when the selection is stale (#316)", () => {
    // A persisted id for a deleted competition, or one belonging to a different
    // user, is not in the visible list — it must not survive.
    expect(pickActiveCompetitionId("gone", ids)).toBe("a");
  });

  it("returns null when there are no competitions", () => {
    expect(pickActiveCompetitionId("a", [])).toBeNull();
    expect(pickActiveCompetitionId(null, [])).toBeNull();
  });
});
