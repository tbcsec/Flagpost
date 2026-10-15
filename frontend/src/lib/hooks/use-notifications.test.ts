import { describe, expect, it } from "vitest";

import { judgingFrameInvalidations } from "@/lib/hooks/use-notifications";

describe("judgingFrameInvalidations", () => {
  it("refetches the competition's judgings when one changes state", () => {
    expect(judgingFrameInvalidations({ competition_id: "c1", verdict: null })).toEqual([
      ["judge", "judgings", "c1"],
    ]);
  });

  it("also refetches the challenges on an accept, whose solved flag changed", () => {
    expect(judgingFrameInvalidations({ competition_id: "c1", verdict: "accepted" })).toEqual([
      ["judge", "judgings", "c1"],
      ["challenges", "c1"],
    ]);
    expect(judgingFrameInvalidations({ competition_id: "c1", verdict: "wrong_answer" })).toHaveLength(1);
  });

  it("ignores a frame without a competition", () => {
    expect(judgingFrameInvalidations({ verdict: "accepted" })).toEqual([]);
  });
});
