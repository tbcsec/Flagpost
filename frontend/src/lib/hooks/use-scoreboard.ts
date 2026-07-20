"use client";

// One hook module per domain (ARCHITECTURE.md §8). Scoreboard (Phase 7).

import { useQuery, useQueryClient } from "@tanstack/react-query";
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
          },
        );
      },
    });
    return () => socket.close();
  }, [isAuthenticated, competitionId, queryClient]);

  return { ...query, socketStatus };
}
