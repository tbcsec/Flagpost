// Pure helpers for venue/projector mode (#77), kept out of the component so the
// rotation cadence and the first-blood-splash diff are unit-testable without
// rendering or timers.

import type { PublicRecentSolve } from "@/lib/types";

export const DEFAULT_ROTATE_SECONDS = 15;
// Bounds for the `?interval=` override — fast enough to be lively, slow enough
// that a spectator can actually read a slide; guards a hostile/garbage value.
const MIN_ROTATE_SECONDS = 5;
const MAX_ROTATE_SECONDS = 120;

/** Seconds-per-slide from the `?interval=` query param, clamped to a sane range;
 *  anything missing or unparseable falls back to the 15s default. */
export function parseRotateSeconds(raw: string | null | undefined): number {
  if (!raw) return DEFAULT_ROTATE_SECONDS;
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n)) return DEFAULT_ROTATE_SECONDS;
  return Math.min(MAX_ROTATE_SECONDS, Math.max(MIN_ROTATE_SECONDS, n));
}

/** Advance the rotation index, wrapping; guards an empty slide set. */
export function nextIndex(current: number, count: number): number {
  if (count <= 0) return 0;
  return (current + 1) % count;
}

/** First-blood solves in `solves` not yet in `seen` — the ones that should
 *  splash. Pure: it does not mutate `seen` (the caller records what it shows).
 *
 *  The feed arrives newest-first; the result is reversed to oldest-first so that
 *  when two first bloods land between polls, their splashes queue in the order
 *  they actually happened. Keying on `challenge_id` is safe because a challenge
 *  has exactly one first blood. */
export function pickNewFirstBloods(
  solves: PublicRecentSolve[],
  seen: Set<string>,
): PublicRecentSolve[] {
  return solves
    .filter((s) => s.is_first_blood && !seen.has(s.challenge_id))
    .reverse();
}
