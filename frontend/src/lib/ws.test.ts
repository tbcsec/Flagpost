import { describe, expect, it } from "vitest";

import { backoffDelayMs } from "@/lib/ws";

describe("backoffDelayMs", () => {
  it("grows exponentially with the attempt number", () => {
    // random() = 1 → the full cap for that attempt.
    expect(backoffDelayMs(0, () => 1)).toBe(1_000);
    expect(backoffDelayMs(1, () => 1)).toBe(2_000);
    expect(backoffDelayMs(3, () => 1)).toBe(8_000);
  });

  it("caps at 30s no matter how many attempts", () => {
    expect(backoffDelayMs(10, () => 1)).toBe(30_000);
    expect(backoffDelayMs(50, () => 1)).toBe(30_000);
  });

  it("jitters between half and the full delay", () => {
    // random() = 0 → half the cap; random() = 1 → the cap.
    expect(backoffDelayMs(2, () => 0)).toBe(2_000);
    expect(backoffDelayMs(2, () => 1)).toBe(4_000);
  });
});
