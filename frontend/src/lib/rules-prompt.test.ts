import { describe, expect, it } from "vitest";

import { rulesGateRejection, rulesPromptMode } from "@/lib/rules-prompt";
import type { RichTextDoc } from "@/lib/types";

const DOC: RichTextDoc = {
  type: "doc",
  content: [
    { type: "paragraph", content: [{ type: "text", text: "Be excellent" }] },
  ],
};

describe("rulesPromptMode", () => {
  it("requires acceptance for mandatory, unaccepted rules", () => {
    expect(
      rulesPromptMode({ rules: DOC, display_only: false, accepted: false, exempt: false }),
    ).toBe("accept");
  });

  it("shows display-only rules without gating", () => {
    expect(
      rulesPromptMode({ rules: DOC, display_only: true, accepted: false, exempt: false }),
    ).toBe("display");
  });

  it("stays silent when there are no rules", () => {
    expect(
      rulesPromptMode({ rules: null, display_only: false, accepted: false, exempt: false }),
    ).toBeNull();
  });

  it("stays silent once accepted", () => {
    expect(
      rulesPromptMode({ rules: DOC, display_only: false, accepted: true, exempt: false }),
    ).toBeNull();
  });

  it("stays silent for exempt staff — even display-only", () => {
    expect(
      rulesPromptMode({ rules: DOC, display_only: false, accepted: false, exempt: true }),
    ).toBeNull();
    expect(
      rulesPromptMode({ rules: DOC, display_only: true, accepted: false, exempt: true }),
    ).toBeNull();
  });
});

describe("rulesGateRejection", () => {
  it("parses the structured 403 detail", () => {
    const err = {
      detail: {
        code: "rules_not_accepted",
        competition_id: "comp-1",
        rules: DOC,
        message: "You must accept the competition rules before joining",
      },
    };
    expect(rulesGateRejection(err)).toEqual({
      competitionId: "comp-1",
      rules: DOC,
    });
  });

  it("rejects anything that isn't the rules gate", () => {
    expect(rulesGateRejection(new Error("boom"))).toBeNull();
    expect(rulesGateRejection({ detail: "plain string detail" })).toBeNull();
    expect(rulesGateRejection({ detail: { code: "other" } })).toBeNull();
    expect(
      rulesGateRejection({ detail: { code: "rules_not_accepted" } }),
    ).toBeNull(); // missing competition_id/rules
    expect(rulesGateRejection(null)).toBeNull();
    expect(rulesGateRejection(undefined)).toBeNull();
  });
});
