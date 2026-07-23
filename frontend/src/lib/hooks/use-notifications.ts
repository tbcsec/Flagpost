"use client";

// One hook module per domain (ARCHITECTURE.md §8). In-app notification center
// (§4.4): the current user's own read/unread feed, kept live over the per-user
// `/ws/user/<id>` room so the bell updates without a refresh.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { notificationsApi } from "@/lib/api";
import { getDeliveryPrefs, setDeliveryPrefs } from "@/lib/notification-prefs";
import type { NotificationPreferences } from "@/lib/types";
import { openRoomSocket } from "@/lib/ws";
import { useAuthStore } from "@/stores/auth";

const notificationKeys = {
  all: ["notifications"] as const,
  preferences: ["notifications", "preferences"] as const,
};

// Show an OS notification for an incoming frame when the user opted into
// browser notifications and the browser has granted permission. Best-effort:
// no-op where the Notification API is unavailable or not granted.
function maybeShowBrowserNotification(frame: {
  title?: string;
  body?: string | null;
}): void {
  if (!getDeliveryPrefs().browser) return;
  if (typeof Notification === "undefined" || Notification.permission !== "granted") {
    return;
  }
  try {
    new Notification(frame.title ?? "Notification", {
      body: frame.body ?? undefined,
    });
  } catch {
    /* browser notifications unavailable — non-fatal */
  }
}

/** The current user's notifications, subscribed to their per-user room: a new
 *  notification pushed there invalidates the list (and, with it, the bell), and
 *  surfaces an OS notification when the browser preference is on. */
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
        const frame = data as { type?: string; title?: string; body?: string | null };
        if (frame.type === "notification") {
          queryClient.invalidateQueries({ queryKey: notificationKeys.all });
          maybeShowBrowserNotification(frame);
        }
      },
    });
    return () => socket.close();
  }, [isAuthenticated, userId, queryClient]);

  return query;
}

/** The current user's notification preferences. Kept in the module-level
 *  delivery cache so the ticket sound cue + browser-notification delivery
 *  (which live in other hooks) read the latest values. */
export function useNotificationPreferences() {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  const query = useQuery({
    queryKey: notificationKeys.preferences,
    queryFn: () => notificationsApi.getPreferences(),
    enabled: isAuthenticated,
  });

  useEffect(() => {
    if (query.data) setDeliveryPrefs(query.data);
  }, [query.data]);

  return query;
}

export function useUpdateNotificationPreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (prefs: NotificationPreferences) =>
      notificationsApi.updatePreferences(prefs),
    onSuccess: (saved) => {
      setDeliveryPrefs(saved);
      queryClient.setQueryData(notificationKeys.preferences, saved);
    },
  });
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
