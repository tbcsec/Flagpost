"use client";

// One hook module per domain (ARCHITECTURE.md §8). Announcements (Phase 8).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { announcementsApi } from "@/lib/api";
import type { Announcement, AnnouncementCreate } from "@/lib/types";
import { openRoomSocket } from "@/lib/ws";
import { useAuthStore } from "@/stores/auth";

const announcementKeys = {
  list: (competitionId: string) => ["announcements", competitionId] as const,
};

/** The competition's announcements: REST for the initial load, then the
 *  announcements WebSocket room prepends new ones live into the cache (§8).
 *
 *  `subscribe` gates the socket so the same room isn't opened twice on one page:
 *  the shell's banner subscribes; other readers (e.g. the dashboard widget) pass
 *  `subscribe: false` and get live updates via the shared query cache. */
export function useAnnouncements(
  competitionId: string,
  { subscribe = true }: { subscribe?: boolean } = {},
) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: announcementKeys.list(competitionId),
    queryFn: () => announcementsApi.list(competitionId),
    enabled: isAuthenticated && Boolean(competitionId),
  });

  useEffect(() => {
    if (!subscribe || !isAuthenticated || !competitionId) return;
    const socket = openRoomSocket("announcements", competitionId, {
      onMessage: (data) => {
        const frame = data as {
          type?: string;
          announcement?: Announcement;
          announcements?: Announcement[];
        };
        if (frame.type === "announcement" && frame.announcement) {
          const incoming = frame.announcement;
          queryClient.setQueryData<Announcement[]>(
            announcementKeys.list(competitionId),
            (prev) =>
              prev?.some((a) => a.id === incoming.id)
                ? prev
                : [incoming, ...(prev ?? [])],
          );
        } else if (frame.type === "announcements" && frame.announcements) {
          queryClient.setQueryData<Announcement[]>(
            announcementKeys.list(competitionId),
            frame.announcements,
          );
        }
      },
    });
    return () => socket.close();
  }, [subscribe, isAuthenticated, competitionId, queryClient]);

  return query;
}

export function useCreateAnnouncement(competitionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: AnnouncementCreate) =>
      announcementsApi.create(competitionId, input),
    // The WS frame also arrives, but invalidating keeps the poster's own view
    // correct even if their socket is momentarily down.
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: announcementKeys.list(competitionId),
      }),
  });
}
