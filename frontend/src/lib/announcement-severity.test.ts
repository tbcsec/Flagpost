import { describe, expect, it } from "vitest";

import {
  SEVERITY_ORDER,
  SEVERITY_STYLES,
  severityStyle,
} from "@/lib/announcement-severity";

describe("severityStyle", () => {
  it("returns the matching style for each rung, carrying its label key", () => {
    // Labels themselves live in announcements.severity.* (ADR-0029) — the
    // style carries the effective key callers translate through.
    expect(severityStyle("info").key).toBe("info");
    expect(severityStyle("warning").key).toBe("warning");
    expect(severityStyle("critical").key).toBe("critical");
  });

  it("falls back to info for unknown / missing severities", () => {
    // A newer server could send a rung this build doesn't know about, and
    // pre-#40 rows deserialize without the field at all.
    expect(severityStyle("apocalyptic")).toBe(SEVERITY_STYLES.info);
    expect(severityStyle(undefined)).toBe(SEVERITY_STYLES.info);
    expect(severityStyle(null)).toBe(SEVERITY_STYLES.info);
  });

  it("only critical persists until dismissed", () => {
    expect(severityStyle("info").autoDismissMs).toBeGreaterThan(0);
    expect(severityStyle("warning").autoDismissMs).toBeGreaterThan(0);
    // A self-dismissing "critical" would undercut the whole tier (#40).
    expect(severityStyle("critical").autoDismissMs).toBeNull();
  });

  it("uses design tokens, never raw colour values (§9)", () => {
    for (const style of Object.values(SEVERITY_STYLES)) {
      for (const cls of [style.accent, style.surface, style.chip]) {
        expect(cls).not.toMatch(/#[0-9a-fA-F]{3,8}/);
        expect(cls).not.toMatch(/rgb|hsl\(/);
      }
    }
  });

  it("orders the ladder by ascending urgency and covers every style", () => {
    expect(SEVERITY_ORDER).toEqual(["info", "warning", "critical"]);
    expect(Object.keys(SEVERITY_STYLES).sort()).toEqual(
      [...SEVERITY_ORDER].sort(),
    );
  });
});
