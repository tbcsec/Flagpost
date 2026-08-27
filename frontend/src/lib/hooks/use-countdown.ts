"use client";

import { useEffect, useState } from "react";

import { parseServerDate } from "@/lib/datetime";

/** Seconds remaining until `iso`, re-computed every second so a caller can show
 *  a live "expires in 12:34". Returns `null` when `iso` is null (nothing to
 *  count down), and floors at 0 once the moment has passed. */
export function useCountdown(iso: string | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!iso) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [iso]);
  if (!iso) return null;
  return Math.max(0, Math.round((parseServerDate(iso).getTime() - now) / 1000));
}

/** Format a whole number of seconds as `M:SS` (or `H:MM:SS` past an hour). */
export function formatCountdown(totalSeconds: number): string {
  const s = Math.max(0, totalSeconds);
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(seconds)}`
    : `${minutes}:${pad(seconds)}`;
}
