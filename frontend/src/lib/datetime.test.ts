import { describe, expect, it } from "vitest";

import { parseServerDate, relativeTime } from "@/lib/datetime";

describe("parseServerDate", () => {
  it("treats a tz-less timestamp as UTC", () => {
    // Naive string → parsed as UTC, not local.
    const d = parseServerDate("2026-07-20T23:44:44");
    expect(d.toISOString()).toBe("2026-07-20T23:44:44.000Z");
  });

  it("respects an explicit offset", () => {
    expect(parseServerDate("2026-07-20T23:44:44Z").toISOString()).toBe(
      "2026-07-20T23:44:44.000Z",
    );
    expect(parseServerDate("2026-07-20T23:44:44+00:00").toISOString()).toBe(
      "2026-07-20T23:44:44.000Z",
    );
  });
});

describe("relativeTime", () => {
  it("formats recent timestamps", () => {
    const now = new Date();
    const fiveMinAgo = new Date(now.getTime() - 5 * 60_000).toISOString();
    expect(relativeTime(fiveMinAgo)).toBe("5m ago");
    const twoHoursAgo = new Date(now.getTime() - 2 * 3_600_000).toISOString();
    expect(relativeTime(twoHoursAgo)).toBe("2h ago");
  });
});
