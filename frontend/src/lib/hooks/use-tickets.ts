"use client";

// One hook module per domain (ARCHITECTURE.md §8). Support tickets (§4.4).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ticketAttachmentsApi, ticketsApi } from "@/lib/api";
import { playTicketCue } from "@/lib/audio-cue";
import type { TicketStatus } from "@/lib/types";
import { openRoomSocket } from "@/lib/ws";
import { useAuthStore } from "@/stores/auth";

const ticketKeys = {
  all: (competitionId: string) => ["tickets", competitionId] as const,
  list: (competitionId: string, status?: TicketStatus) =>
    ["tickets", competitionId, "list", status ?? "all"] as const,
  detail: (competitionId: string, ticketId: string) =>
    ["tickets", competitionId, "detail", ticketId] as const,
};

export function useTickets(competitionId: string, status?: TicketStatus) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  return useQuery({
    queryKey: ticketKeys.list(competitionId, status),
    queryFn: () => ticketsApi.list(competitionId, status),
    enabled: isAuthenticated && Boolean(competitionId),
  });
}

/** Staff-only live queue: refetch the ticket lists when a ticket is created,
 *  assigned or resolved, and play the §4.4 cue on a newly-opened ticket. */
export function useSupportQueueLive(competitionId: string, enabled: boolean) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!enabled || !isAuthenticated || !competitionId) return;
    const socket = openRoomSocket("support", competitionId, {
      onMessage: (data) => {
        const frame = data as { type?: string };
        if (frame.type === "ticket_created") playTicketCue();
        queryClient.invalidateQueries({ queryKey: ticketKeys.all(competitionId) });
      },
    });
    return () => socket.close();
  }, [enabled, isAuthenticated, competitionId, queryClient]);
}

/** A single ticket's thread, kept live over its WS room: a reply from the other
 *  side refetches the thread and plays the cue. */
export function useTicket(competitionId: string, ticketId: string | null) {
  const isAuthenticated = useAuthStore((s) => s.status === "authenticated");
  const userId = useAuthStore((s) => s.user?.id);
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ticketKeys.detail(competitionId, ticketId ?? ""),
    queryFn: () => ticketsApi.get(competitionId, ticketId as string),
    enabled: isAuthenticated && Boolean(competitionId) && Boolean(ticketId),
  });

  useEffect(() => {
    if (!isAuthenticated || !competitionId || !ticketId) return;
    const socket = openRoomSocket("ticket", ticketId, {
      onMessage: (data) => {
        const frame = data as { type?: string; author_user_id?: string };
        if (frame.type === "ticket_message" && frame.author_user_id !== userId) {
          playTicketCue();
        }
        // Bodies aren't broadcast — refetch the permission-filtered thread.
        queryClient.invalidateQueries({
          queryKey: ticketKeys.detail(competitionId, ticketId),
        });
        queryClient.invalidateQueries({ queryKey: ticketKeys.all(competitionId) });
      },
    });
    return () => socket.close();
  }, [isAuthenticated, competitionId, ticketId, userId, queryClient]);

  return query;
}

function useInvalidate(competitionId: string) {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({ queryKey: ticketKeys.all(competitionId) });
}

export function useCreateTicket(competitionId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: (input: { subject: string; body: string; challenge_id?: string | null }) =>
      ticketsApi.create(competitionId, input),
    onSuccess: invalidate,
  });
}

export function useReplyTicket(competitionId: string, ticketId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: (input: { body: string; is_internal?: boolean }) =>
      ticketsApi.reply(competitionId, ticketId, input),
    onSuccess: invalidate,
  });
}

export function useAssignTicket(competitionId: string, ticketId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: (assigneeUserId?: string) =>
      ticketsApi.assign(competitionId, ticketId, assigneeUserId),
    onSuccess: invalidate,
  });
}

export function useResolveTicket(competitionId: string, ticketId: string) {
  const invalidate = useInvalidate(competitionId);
  return useMutation({
    mutationFn: () => ticketsApi.resolve(competitionId, ticketId),
    onSuccess: invalidate,
  });
}

/** Attach a screenshot to a message that was just posted (issue #80).
 *
 *  `ticketId` is a mutation variable rather than a hook parameter because the
 *  new-ticket flow doesn't know it until `useCreateTicket` resolves — the
 *  message has to exist before anything can hang off it. */
export function useUploadTicketAttachment(competitionId: string) {
  const invalidate = useInvalidate(competitionId);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      ticketId,
      messageId,
      file,
    }: {
      ticketId: string;
      messageId: string;
      file: File;
    }) => ticketAttachmentsApi.upload(competitionId, ticketId, messageId, file),
    onSuccess: (_data, { ticketId }) => {
      queryClient.invalidateQueries({
        queryKey: ticketKeys.detail(competitionId, ticketId),
      });
      invalidate();
    },
  });
}

export function useDeleteTicketAttachment(competitionId: string, ticketId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (attachmentId: string) =>
      ticketAttachmentsApi.remove(competitionId, ticketId, attachmentId),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ticketKeys.detail(competitionId, ticketId),
      }),
  });
}

/** Load an attachment's bytes as an object URL for `<img src>`.
 *
 *  The API needs a Bearer header, so the image can't be pointed at the URL
 *  directly — we fetch it and hand the browser a `blob:` URL instead (which the
 *  production CSP permits, unlike a cross-origin storage URL). The URL is
 *  revoked when the component unmounts or the attachment changes, otherwise
 *  every preview would leak its buffer for the life of the page. */
export function useAttachmentImage(
  competitionId: string,
  ticketId: string,
  attachmentId: string,
) {
  // One state object tagged with the id it belongs to, so switching attachments
  // is handled by *ignoring* a stale result rather than resetting state from
  // inside the effect (which would trigger a cascading render).
  const [loaded, setLoaded] = useState<{
    id: string;
    url: string | null;
    failed: boolean;
  } | null>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;

    ticketAttachmentsApi
      .content(competitionId, ticketId, attachmentId)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setLoaded({ id: attachmentId, url: objectUrl, failed: false });
      })
      .catch(() => {
        if (!cancelled) setLoaded({ id: attachmentId, url: null, failed: true });
      });

    return () => {
      cancelled = true;
      // Deliberately not shared through the query cache: two components showing
      // the same attachment (thumbnail + lightbox) would otherwise share one
      // object URL, and the first to unmount would revoke it out from under the
      // other. The response itself is HTTP-cached, so re-fetching is cheap.
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [competitionId, ticketId, attachmentId]);

  const current = loaded?.id === attachmentId ? loaded : null;
  return { url: current?.url ?? null, failed: current?.failed ?? false };
}
