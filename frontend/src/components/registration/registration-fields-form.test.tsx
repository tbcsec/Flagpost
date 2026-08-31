import { describe, expect, it } from "vitest";

import type { RegistrationField } from "@/lib/types";

import { missingRequired } from "./registration-fields-form";

function field(over: Partial<RegistrationField>): RegistrationField {
  return {
    id: over.key ?? "f",
    key: over.key ?? "f",
    label: over.key ?? "F",
    field_type: "text",
    options: [],
    required: false,
    position: 0,
    ...over,
  };
}

describe("missingRequired", () => {
  it("ignores optional fields entirely", () => {
    const fields = [field({ key: "a" }), field({ key: "b", field_type: "checkbox" })];
    expect(missingRequired(fields, {})).toBe(false);
  });

  it("flags a required text/select that is empty or whitespace", () => {
    const fields = [field({ key: "size", field_type: "select", required: true })];
    expect(missingRequired(fields, {})).toBe(true);
    expect(missingRequired(fields, { size: "   " })).toBe(true);
    expect(missingRequired(fields, { size: "M" })).toBe(false);
  });

  it("requires a checkbox to be explicitly true (consent must be ticked)", () => {
    const fields = [field({ key: "consent", field_type: "checkbox", required: true })];
    expect(missingRequired(fields, {})).toBe(true);
    expect(missingRequired(fields, { consent: false })).toBe(true);
    expect(missingRequired(fields, { consent: true })).toBe(false);
  });
});
