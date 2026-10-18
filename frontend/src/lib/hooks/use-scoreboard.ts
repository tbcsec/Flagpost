"use client";

// One hook module per domain (ARCHITECTURE.md §8). Scoreboard (Phase 7).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { scoreboardApi } from "@/lib/api";
import type { Scoreboard } from "@/lib/types";
import { openRoomSocket, type RoomSocketStatus } from "@/lib/ws";
import { useAuthStore } from "@/stores/auth";

// `live` is the staff view during a freeze (#501): its own cache entry, so the
// shared (competitor) board and the live one never overwrite each other.
const scoreboardKeys = {
  detail: (competitionId: string, live: boolean) =>
    ["scoreboard", competitionId, live ? "live" : "shared"] as const,
  timeline: (competitionId: string, bracket: string | null, live: boolean) =>
    ["scoreboard-timeline", competitionId, bracket, live] as const,
};

/** The live scoreboard: REST for the initial load, then the competition's
 *  WebSocket room pushes fresh boards straight into the query cache — no
 *  polling (§8). Also reports the socket status so the page can show a live
 *  indicator.
 *
 *  `live` (staff, #501): read the standings past a freeze, from the staff-only
 *  `scoreboard_live` room, which keeps moving while the shared room holds the
 *  frozen board. The server honours it only for a scoreboard_freeze holder. */
export function useScoreboard(
  competitionId: string,
  { live = false }: { live?: boolean } = {},
) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  const queryClient = useQueryClient();
  const [socketStatus, setSocketStatus] = useState<RoomSocketStatus>("closed");

  const query = useQuery({
    queryKey: scoreboardKeys.detail(competitionId, live),
    queryFn: () => scoreboardApi.get(competitionId, null, live),
    enabled: isAuthenticated && Boolean(competitionId),
    // Switching to the live view keeps the current board on screen (banner and
    // Freeze control included) until the live one loads. Never the other way:
    // live standings must not stand in for the frozen view — that switch is
    // how a shared screen is made safe. Nor across competitions.
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1] === competitionId && (live || !previous?.live)
        ? previous
        : undefined,
  });

  useEffect(() => {
    if (!isAuthenticated || !competitionId) return;
    const room = live ? "scoreboard_live" : "scoreboard";
    const socket = openRoomSocket(room, competitionId, {
      onStatus: setSocketStatus,
      onMessage: (data) => {
        const frame = data as { type?: string } & Scoreboard;
        if (frame.type !== "scoreboard") return;
        const board: Scoreboard = {
          competition_id: frame.competition_id,
          mode: frame.mode,
          entries: frame.entries,
          frozen: frame.frozen,
          frozen_at: frame.frozen_at,
          live: frame.live ?? false,
          brackets: frame.brackets,
        };
        queryClient.setQueryData<Scoreboard>(
          scoreboardKeys.detail(competitionId, live),
          board,
        );
        // The other view gets no frames while this one is open, so drop it:
        // switching views then loads fresh instead of showing a board from
        // before a freeze or unfreeze that happened meanwhile.
        queryClient.removeQueries({
          queryKey: scoreboardKeys.detail(competitionId, !live),
          exact: true,
        });
        if (board.live) {
          // Frozen for competitors: the activity room that refreshes the chart
          // is silent, so the staff chart follows this room instead.
          queryClient.invalidateQueries({
            queryKey: ["scoreboard-timeline", competitionId],
          });
        }
      },
    });
    return () => socket.close();
  }, [isAuthenticated, competitionId, live, queryClient]);

  return { ...query, socketStatus };
}

/** Cumulative score-over-time for the top-N entrants (#348), the chart beside
 *  the standings. A plain query (not its own socket): it shares the shell's
 *  `activity` room, which invalidates the `scoreboard-timeline` key on every
 *  scoring event, so a mounted chart refetches its freeze/bracket-scoped slice
 *  without a second WebSocket. Bracket null = the whole board. */
export function useScoreboardTimeline(
  competitionId: string,
  bracket: string | null = null,
  live = false,
) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: scoreboardKeys.timeline(competitionId, bracket, live),
    queryFn: () => scoreboardApi.timeline(competitionId, bracket, live),
    enabled: isAuthenticated && Boolean(competitionId),
  });
}

/** Freeze/unfreeze the public scoreboard (scoreboard_freeze). The response is
 *  the fresh board, written straight into the cache. */
export function useFreezeScoreboard(competitionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (freeze: boolean) =>
      freeze
        ? scoreboardApi.freeze(competitionId)
        : scoreboardApi.unfreeze(competitionId),
    onSuccess: (board) => {
      // The competition's scoreboard_frozen_at changed — refresh it so the
      // settings Controls toggle (Freeze/Unfreeze) reflects the new state.
      queryClient.invalidateQueries({ queryKey: ["competitions"] });
      // The response is the live board. Unfrozen, that's everyone's board;
      // frozen, the shared view refetches the frozen one — awaited, so the
      // control stays pending until it shows Unfreeze.
      queryClient.setQueryData(scoreboardKeys.detail(competitionId, true), board);
      if (board.live) {
        return queryClient.invalidateQueries({
          queryKey: scoreboardKeys.detail(competitionId, false),
        });
      }
      queryClient.setQueryData(scoreboardKeys.detail(competitionId, false), board);
    },
  });
}
