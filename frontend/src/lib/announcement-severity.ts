// Announcement severity presentation (#40, ARCHITECTURE.md §9).
//
// One source of truth for how each rung of the urgency ladder looks and
// behaves, so the banner, the composer and the dashboard widget can't drift.
// Pure — no React — and colours are design tokens only (§9 bans raw hex).

import type { AnnouncementSeverity } from "@/lib/types";

export interface SeverityStyle {
  /** The effective severity — the key callers translate the label through
   *  (`t(`severity.${style.key}`)`, announcements.severity.*). Carried here so
   *  the unknown-severity fallback below stays in one place (ADR-0029). */
  key: AnnouncementSeverity;
  /** Accent bar + icon colour. */
  accent: string;
  /** Banner surface + border. */
  surface: string;
  /** Chip treatment for list/widget rows. */
  chip: string;
  /**
   * How long the banner dwells before auto-dismissing, in ms — `null` means it
   * stays until dismissed. A self-dismissing "critical" would undercut the
   * whole tier, so that one requires an explicit close (#40).
   */
  autoDismissMs: number | null;
}

const DEFAULT_DWELL_MS = 30_000;

export const SEVERITY_STYLES: Record<AnnouncementSeverity, SeverityStyle> = {
  info: {
    key: "info",
    accent: "text-primary",
    surface: "border-primary/30 bg-primary/10",
    chip: "bg-primary/15 text-primary",
    autoDismissMs: DEFAULT_DWELL_MS,
  },
  warning: {
    key: "warning",
    accent: "text-warning",
    surface: "border-warning/40 bg-warning/10",
    chip: "bg-warning/15 text-warning",
    autoDismissMs: DEFAULT_DWELL_MS,
  },
  critical: {
    key: "critical",
    accent: "text-destructive",
    surface: "border-destructive/50 bg-destructive/10",
    chip: "bg-destructive/15 text-destructive",
    autoDismissMs: null, // stays until explicitly dismissed
  },
};

/** Style for a severity, falling back to `info` for anything unrecognized (a
 *  newer server could send a rung this build doesn't know about). */
export function severityStyle(severity: string | null | undefined): SeverityStyle {
  return SEVERITY_STYLES[severity as AnnouncementSeverity] ?? SEVERITY_STYLES.info;
}

/** The ladder in display order — drives the composer's severity selector. */
export const SEVERITY_ORDER: AnnouncementSeverity[] = ["info", "warning", "critical"];
