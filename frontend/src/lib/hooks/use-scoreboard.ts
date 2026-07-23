"use client";

// One hook module per domain (ARCHITECTURE.md §8). Scoreboard (Phase 7).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { scoreboardApi } from "@/lib/api";
import type { Scoreboard } from "@/lib/types";
import { openRoomSocket, type RoomSocketStatus } from "@/lib/ws";
import { useAuthStore } from "@/stores/auth";

const scoreboardKeys = {
  detail: (competitionId: string) => ["scoreboard", competitionId] as const,
};

/** The live scoreboard: REST for the initial load, then the competition's
 *  WebSocket room pushes fresh boards straight into the query cache — no
 *  polling (§8). Also reports the socket status so the page can show a live
 *  indicator. */
export function useScoreboard(competitionId: string) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  const queryClient = useQueryClient();
  const [socketStatus, setSocketStatus] = useState<RoomSocketStatus>("closed");

  const query = useQuery({
    queryKey: scoreboardKeys.detail(competitionId),
    queryFn: () => scoreboardApi.get(competitionId),
    enabled: isAuthenticated && Boolean(competitionId),
  });

  useEffect(() => {
    if (!isAuthenticated || !competitionId) return;
    const socket = openRoomSocket("scoreboard", competitionId, {
      onStatus: setSocketStatus,
      onMessage: (data) => {
        const frame = data as { type?: string } & Scoreboard;
        if (frame.type !== "scoreboard") return;
        queryClient.setQueryData<Scoreboard>(
          scoreboardKeys.detail(competitionId),
          {
            competition_id: frame.competition_id,
            mode: frame.mode,
            entries: frame.entries,
            frozen: frame.frozen,
            frozen_at: frame.frozen_at,
          },
        );
      },
    });
    return () => socket.close();
  }, [isAuthenticated, competitionId, queryClient]);

  return { ...query, socketStatus };
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
    onSuccess: (board) =>
      queryClient.setQueryData(scoreboardKeys.detail(competitionId), board),
  });
}
