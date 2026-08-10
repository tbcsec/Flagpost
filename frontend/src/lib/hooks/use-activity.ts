"use client";

// One hook module per domain (ARCHITECTURE.md §8). The activity room (#18):
// one shell-level socket per active competition that turns backend event pings
// into throttled query invalidations, so every surface — dashboard widgets,
// challenge cards, rosters, analytics — refreshes live without polling. The
// event → query-key mapping and the throttle live in lib/live.ts (pure,
// unit-tested); this hook only owns the socket lifecycle.

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import {
  ACTIVITY_JITTER_MS,
  ACTIVITY_THROTTLE_MS,
  createThrottledInvalidator,
  keysForActivity,
} from "@/lib/live";
import { openRoomSocket } from "@/lib/ws";
import { useAuthStore } from "@/stores/auth";

/** Subscribe the query cache to a competition's activity room. Mounted once in
 *  the app shell (beside the notification bell) — pages never open their own. */
export function useActivityLive(competitionId: string | null | undefined) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!isAuthenticated || !competitionId) return;
    // Jitter the refetches: a solve pings every client at once, so without it
    // all N fire their REST refetch simultaneously and hammer the DB pool (#175).
    const invalidator = createThrottledInvalidator(
      (key) => queryClient.invalidateQueries({ queryKey: key }),
      ACTIVITY_THROTTLE_MS,
      { jitterMs: ACTIVITY_JITTER_MS },
    );
    const socket = openRoomSocket("activity", competitionId, {
      onMessage: (data) => {
        const frame = data as { type?: string; event?: string };
        if (frame.type !== "activity" || !frame.event) return;
        invalidator.push(keysForActivity(frame.event, competitionId));
      },
    });
    return () => {
      socket.close();
      invalidator.dispose();
    };
  }, [isAuthenticated, competitionId, queryClient]);
}
