// Live-update wiring for the per-competition activity room (#18, §4.1).
//
// The backend fans out tiny `{type: "activity", event: "<§3.2 name>"}` pings —
// ids only, never data — and this module decides what each event means for the
// query cache. Pure logic (no React), mirroring the lib/data-table.ts split so
// the mapping and the throttle are unit-testable.
//
// Invalidation, not cache-writing: every stale surface here is per-user
// filtered (solved state, locks, MC attempts, role-scoped stats), so clients
// refetch their own permission-filtered REST slice. `invalidateQueries` only
// refetches *active* (mounted) queries — background pages are merely marked
// stale and fetch fresh on navigation, which is exactly the behaviour we want
// from a shell-level socket.

import type { QueryKey } from "@tanstack/react-query";

/** Leading + trailing throttle window per query key. A lone event lands
 *  instantly; a burst (mass solves, a busy competition) collapses to at most
 *  one refetch per key per window. */
export const ACTIVITY_THROTTLE_MS = 2_500;

/** Spread each invalidation's refetch across a random 0..N ms so an event that
 *  pings every connected client (a solve → all N clients) doesn't fire N
 *  simultaneous REST requests at the backend (#175). The per-key throttle caps
 *  *how often* a client refetches; the jitter smooths *when* the whole room
 *  does, flattening the concurrency spike that saturated the DB pool. */
export const ACTIVITY_JITTER_MS = 500;

/** The dashboard's data widgets — deliberately excludes the layout key, so a
 *  live ping never touches an in-progress layout edit. */
function dashboardData(cid: string): QueryKey[] {
  return [
    ["dashboard", cid, "stats"],
    ["dashboard", cid, "recent-solves"],
    ["dashboard", cid, "challenge-health"],
    ["dashboard", cid, "me"],
  ];
}

/** Rosters: the participants table (individual mode) and teams (team mode);
 *  join/points activity moves both plus the participant-count stat tiles. */
function rosters(cid: string): QueryKey[] {
  return [
    ["participants", cid],
    ["teams", cid],
    ["dashboard", cid, "stats"],
    ["analytics", cid],
  ];
}

// What each §3.2 activity event invalidates. Keys are prefixes: ["challenges",
// cid] covers the browse list, any open dialog detail, and its solver list.
// An event absent here is a no-op — the map is the frontend's allowlist, so a
// future backend event degrades to nothing rather than a wild refetch.
const ACTIVITY_INVALIDATIONS: Record<string, (cid: string) => QueryKey[]> = {
  // A solve moves the dashboard widgets, analytics and standings — but NOT the
  // challenge list: that card's public solve_count + value now arrive as a
  // delta on the ping and are patched in place (#188, applyChallengeDelta), so
  // the ~N watchers don't each refetch the whole list (the 4:1 refetch storm).
  // The solver still refreshes its own per-user state (solved/locked) via the
  // submit mutation. Under a freeze the delta is omitted and use-activity falls
  // back to refetching ["challenges", cid].
  "challenge.solved": (cid) => [
    ...dashboardData(cid),
    ["analytics", cid],
    ["participants", cid],
  ],
  // Attempts (incl. failures) move staff counters only — deliberately NOT the
  // challenge list: it's the heaviest refetch, attempts are the most frequent
  // event, and someone else's wrong guess doesn't change your cards.
  "challenge.attempted": (cid) => [
    ["dashboard", cid, "stats"],
    ["dashboard", cid, "challenge-health"],
    ["analytics", cid],
  ],
  // Authoring changes what competitors can see + the published-count tile.
  "challenge.created": (cid) => [["challenges", cid], ["dashboard", cid, "stats"]],
  "challenge.updated": (cid) => [["challenges", cid]],
  "challenge.published": (cid) => [
    ["challenges", cid],
    ...dashboardData(cid),
    ["analytics", cid],
  ],
  "challenge.deleted": (cid) => [
    ["challenges", cid],
    ...dashboardData(cid),
    ["analytics", cid],
  ],
  "challenge.guesses_reset": (cid) => [["challenges", cid]],
  "challenge.rated": (cid) => [["challenge-ratings", cid], ["analytics", cid]],
  "challenge.hint_requested": (cid) => [["analytics", cid]],
  "hint.released": (cid) => [["hints", cid], ["challenges", cid]],
  "category.created": (cid) => [["categories", cid], ["challenges", cid]],
  "category.deleted": (cid) => [["categories", cid], ["challenges", cid]],
  // Points from outside the submit path: adjustments and awards move
  // standings and your rank tile (the scoreboard has its own room).
  "score.adjusted": (cid) => [
    ["participants", cid],
    ["dashboard", cid, "me"],
    ["analytics", cid],
  ],
  "achievement.awarded": (cid) => [
    ["participants", cid],
    ["dashboard", cid, "me"],
    ["analytics", cid],
  ],
  "competition.member_joined": rosters,
  // Pause toggles, schedule edits, vocab changes — the banner goes live.
  "competition.updated": () => [["competitions"]],
  // Start/Stop (#221) re-gate access: refetch the competition (its status drives
  // the gate) plus the challenge list and scoreboard so a competitor's closed
  // message flips to the live surfaces (and back) the moment a judge acts.
  "competition.started": (cid) => [["competitions"], ["challenges", cid], ["scoreboard", cid]],
  "competition.ended": (cid) => [["competitions"], ["challenges", cid], ["scoreboard", cid]],
  "team.created": rosters,
  "team.member_joined": rosters,
  "team.member_left": rosters,
  "team.deleted": rosters,
  // The board room updates itself; freeze only re-slants rank-derived reads.
  "scoreboard.frozen": (cid) => [["dashboard", cid, "me"], ["participants", cid]],
  "scoreboard.unfrozen": (cid) => [["dashboard", cid, "me"], ["participants", cid]],
  // Module toggles re-gate the nav live (shared ["modules", id] query key).
  "module.enabled": (cid) => [["modules", cid]],
  "module.disabled": (cid) => [["modules", cid]],
  "survey.opened": (cid) => [["surveys", cid]],
  "survey.submitted": (cid) => [["surveys", cid]],
};

/** The query keys an activity event invalidates; empty for unknown events. */
export function keysForActivity(event: string, competitionId: string): QueryKey[] {
  return ACTIVITY_INVALIDATIONS[event]?.(competitionId) ?? [];
}

/** Patch a cached challenge list in place from a solve delta (#188): update the
 *  affected challenge's public `solve_count` (and `value`, for dynamic scoring)
 *  without refetching the whole list. Returns the original reference when
 *  nothing matches, so React Query skips a needless re-render. Generic over the
 *  row shape so it stays pure and unit-testable. */
export function applyChallengeDelta<
  T extends { id: string; solve_count: number; value: number },
>(
  list: T[] | undefined,
  challengeId: string,
  solveCount: number,
  value: number | undefined,
): T[] | undefined {
  if (!list) return list;
  let changed = false;
  const next = list.map((c) => {
    if (c.id !== challengeId) return c;
    changed = true;
    return { ...c, solve_count: solveCount, ...(value != null ? { value } : {}) };
  });
  return changed ? next : list;
}

export interface ThrottledInvalidator {
  push: (keys: QueryKey[]) => void;
  dispose: () => void;
}

interface Window_ {
  timer: ReturnType<typeof setTimeout>;
  /** A hit arrived while the window was open — fire once more when it closes. */
  pending: QueryKey | null;
}

/** Optional tuning. `jitterMs` (default 0) spreads each invalidation across a
 *  random 0..jitterMs delay so a room-wide ping doesn't fire N simultaneous
 *  refetches; `random` is injectable so the jitter is deterministic in tests. */
export interface ThrottleOptions {
  jitterMs?: number;
  random?: () => number;
}

/** Per-key leading+trailing throttle: the first hit invalidates immediately;
 *  further hits inside the window coalesce into one trailing invalidation
 *  (which reopens the window, so a steady stream fires at most once per
 *  `throttleMs` per key and the last event is never lost). With `jitterMs`,
 *  each invalidation is delayed a random 0..jitterMs to flatten the room-wide
 *  refetch spike (#175). */
export function createThrottledInvalidator(
  invalidate: (key: QueryKey) => void,
  throttleMs: number = ACTIVITY_THROTTLE_MS,
  { jitterMs = 0, random = Math.random }: ThrottleOptions = {},
): ThrottledInvalidator {
  const windows = new Map<string, Window_>();
  const jitterTimers = new Set<ReturnType<typeof setTimeout>>();

  function fire(key: QueryKey): void {
    if (jitterMs <= 0) {
      invalidate(key);
      return;
    }
    const t = setTimeout(() => {
      jitterTimers.delete(t);
      invalidate(key);
    }, random() * jitterMs);
    jitterTimers.add(t);
  }

  function open(id: string, key: QueryKey): void {
    fire(key);
    windows.set(id, {
      timer: setTimeout(() => close(id), throttleMs),
      pending: null,
    });
  }

  function close(id: string): void {
    const window = windows.get(id);
    windows.delete(id);
    if (window?.pending) open(id, window.pending);
  }

  return {
    push(keys: QueryKey[]): void {
      for (const key of keys) {
        const id = JSON.stringify(key);
        const window = windows.get(id);
        if (window) window.pending = key;
        else open(id, key);
      }
    },
    dispose(): void {
      for (const window of windows.values()) clearTimeout(window.timer);
      for (const t of jitterTimers) clearTimeout(t);
      jitterTimers.clear();
      windows.clear();
    },
  };
}
