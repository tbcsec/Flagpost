"use client";

import { useTranslations } from "next-intl";

import { parseServerDate } from "@/lib/datetime";

/** Translated "just now" / "5m ago" / "3h ago" / "2d ago" (common.time.*).
 *  The hook returns a formatter so call sites keep the `rel(iso)` shape the
 *  pure `relativeTime` had; that pure helper survives (English-only) for the
 *  not-yet-extracted surfaces and is retired with them (ADR-0029). */
export function useRelativeTime(): (iso: string) => string {
  const t = useTranslations("common.time");
  return (iso: string) => {
    const diff = Date.now() - parseServerDate(iso).getTime();
    const mins = Math.round(diff / 60000);
    if (mins < 1) return t("justNow");
    if (mins < 60) return t("minutesAgo", { count: mins });
    const hours = Math.round(mins / 60);
    if (hours < 24) return t("hoursAgo", { count: hours });
    return t("daysAgo", { count: Math.round(hours / 24) });
  };
}
