"use client";

// One hook module per domain (ARCHITECTURE.md §8). In-app notification center
// (§4.4): the current user's own read/unread feed, kept live over the per-user
// `/ws/user/<id>` room so the bell updates without a refresh.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { notificationsApi } from "@/lib/api";
import { openRoomSocket } from "@/lib/ws";
import { useAuthStore } from "@/stores/auth";

const notificationKeys = {
  all: ["notifications"] as const,
};

/** The current user's notifications, subscribed to their per-user room: a new
 *  notification pushed there invalidates the list (and, with it, the bell). */
export function useNotifications() {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  const userId = useAuthStore((s) => s.user?.id);
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: notificationKeys.all,
    queryFn: () => notificationsApi.list(),
    enabled: isAuthenticated,
  });

  useEffect(() => {
    if (!isAuthenticated || !userId) return;
    const socket = openRoomSocket("user", userId, {
      onMessage: (data) => {
        const frame = data as { type?: string };
        if (frame.type === "notification") {
          queryClient.invalidateQueries({ queryKey: notificationKeys.all });
        }
      },
    });
    return () => socket.close();
  }, [isAuthenticated, userId, queryClient]);

  return query;
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: notificationKeys.all }),
  });
}

export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: notificationKeys.all }),
  });
}
