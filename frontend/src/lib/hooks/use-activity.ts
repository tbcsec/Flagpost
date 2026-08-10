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
  applyChallengeDelta,
  createThrottledInvalidator,
  keysForActivity,
} from "@/lib/live";
import { openRoomSocket } from "@/lib/ws";
import type { Challenge } from "@/lib/types";
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
        const frame = data as {
          type?: string;
          event?: string;
          challenge_id?: string;
          solve_count?: number;
          value?: number;
          team_id?: string;
        };
        if (frame.type !== "activity" || !frame.event) return;
        // Solve delta (#188): patch the affected challenge card in place from
        // the broadcast's public solve_count/value instead of refetching the
        // whole list. When the delta is absent (a frozen competition), fall
        // back to invalidating the list so the client refetches its frozen
        // slice.
        if (frame.event === "challenge.solved" && frame.challenge_id) {
          if (typeof frame.solve_count !== "number") {
            // No delta (frozen board / hidden challenge) — refetch the list
            // (the prefix also covers any open detail dialog).
            queryClient.invalidateQueries({
              queryKey: ["challenges", competitionId],
            });
          } else {
            // In team mode, if *our own* team solved it, our shared
            // solved/locked state changed — refetch the full list for correct
            // per-user state. Only the solver's teammates take this path (the
            // solver already refetched via the submit mutation); everyone else
            // just patches, so the room-wide storm stays gone.
            const myTeam = queryClient.getQueryData<{ id: string } | null>([
              "teams",
              competitionId,
              "me",
            ]);
            if (myTeam && frame.team_id && frame.team_id === myTeam.id) {
              queryClient.invalidateQueries({
                queryKey: ["challenges", competitionId],
              });
            } else {
              // Another subject solved it: only the public solve_count/value
              // changed for me — patch the card in place, and refresh just this
              // challenge's detail subkey so an *open* dialog's solver list
              // updates (only clients with that dialog mounted refetch).
              queryClient.setQueryData<Challenge[]>(
                ["challenges", competitionId],
                (old) =>
                  applyChallengeDelta(
                    old,
                    frame.challenge_id!,
                    frame.solve_count!,
                    frame.value,
                  ),
              );
              queryClient.invalidateQueries({
                queryKey: ["challenges", competitionId, frame.challenge_id],
              });
            }
          }
        }
        invalidator.push(keysForActivity(frame.event, competitionId));
      },
    });
    return () => {
      socket.close();
      invalidator.dispose();
    };
  }, [isAuthenticated, competitionId, queryClient]);
}
