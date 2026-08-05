"use client";

// One hook module per domain (ARCHITECTURE.md §8) for the AI assistants (#98,
// ADR-0023). Two surfaces live here: the admin provider config (Admin → Site
// settings → AI) and the administrator assistant's conversation controller,
// which streams a turn's answer over the `ai` WS room while the POST persists
// it (best-effort streaming, ADR-0023 Phase 2).

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, aiAdminApi, aiApi } from "@/lib/api";
import { openRoomSocket, type RoomSocketHandle } from "@/lib/ws";
import type { AiSettingsUpdate } from "@/lib/types";

// --- admin provider config ---------------------------------------------------

const AI_SETTINGS_KEY = ["ai", "settings"] as const;

export function useAiSettings() {
  return useQuery({
    queryKey: AI_SETTINGS_KEY,
    queryFn: aiAdminApi.get,
    staleTime: 60_000,
  });
}

export function useUpdateAiSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: AiSettingsUpdate) => aiAdminApi.update(input),
    onSuccess: (data) => queryClient.setQueryData(AI_SETTINGS_KEY, data),
  });
}

/** Probe the saved provider config. Not cached — it makes a live outbound call,
 *  so it only ever runs on an explicit click. */
export function useTestAiConnection() {
  return useMutation({ mutationFn: () => aiAdminApi.testConnection() });
}

// --- assistant availability + usage -----------------------------------------

/** Whether to show the assistant launcher here. Pass `enabled` from a
 *  client-side staff check so a competitor never fires the request. */
export function useAiAvailability(competitionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["ai", "availability", competitionId],
    queryFn: () => aiApi.availability(competitionId as string),
    enabled: Boolean(competitionId) && enabled,
    staleTime: 5 * 60_000,
  });
}

/** Per-competition token totals — the "surprise bill" indicator in the panel. */
export function useAiUsage(competitionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["ai", "usage", competitionId],
    queryFn: () => aiApi.usage(competitionId as string),
    enabled: Boolean(competitionId) && enabled,
    staleTime: 30_000,
  });
}

// --- conversation controller (streaming chat) -------------------------------

export interface AiChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

/** The admin-assistant chat for `competitionId`. Call `ensureStarted()` (e.g.
 *  when the panel first opens) to create a conversation; it then keeps one `ai`
 *  WS socket for that conversation's lifetime, and on each `send` streams the
 *  answer into `streaming` (live) before finalising it from the POST response —
 *  which the backend guarantees matches the streamed text.
 *
 *  The assistant is competition-scoped, so the caller must key its component by
 *  `competitionId`: a switch remounts this hook fresh rather than mutating the
 *  thread in place. */
export function useAiChat(competitionId: string | null) {
  const queryClient = useQueryClient();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AiChatMessage[]>([]);
  // null when idle; a (possibly empty) string while a turn is generating.
  const [streaming, setStreaming] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [closed, setClosed] = useState(false);

  const socketOpenRef = useRef(false);
  // Gate the socket's onMessage: only accumulate chunks during an active turn,
  // so a stray frame can't append to a finished answer. This gate carries no
  // turn identity, and the WS chunk stream and the HTTP POST are independent
  // transports: a trailing chunk from turn N that the browser delivers *after*
  // turn N's POST resolved but *after* turn N+1 has re-opened the gate could
  // prepend to turn N+1's live text. That needs sub-frame timing between two
  // sockets plus an immediate human re-send, and it self-heals when turn N+1's
  // POST overwrites `streaming` with the authoritative content — the same
  // best-effort-streaming trade-off the backend documents. A full fix needs the
  // server to tag chunks with their turn id; deferred as not worth that here.
  const acceptingRef = useRef(false);
  const seqRef = useRef(0);
  // Ref latches, not React state: state can't gate *synchronous* re-entry (two
  // calls in one tick both read the pre-commit value), so these guard against a
  // double create / double send.
  const startingRef = useRef(false);
  const sendingRef = useRef(false);
  // The live conversation id, readable synchronously after an await to detect a
  // mid-flight swap (startNew) the send closure wouldn't otherwise see.
  const conversationIdRef = useRef<string | null>(null);
  // Resolvers waiting for the socket to authenticate, flushed by onStatus — so
  // readiness is an event, not a poll.
  const readyWaitersRef = useRef<Array<() => void>>([]);

  // One socket per conversation. Chunks stream in here; completion comes from
  // the POST, so `done`/`error` frames need no state handling (the POST's
  // resolve/reject is authoritative).
  useEffect(() => {
    if (!conversationId) return;
    socketOpenRef.current = false;
    const socket: RoomSocketHandle = openRoomSocket("ai", conversationId, {
      onStatus: (status) => {
        const open = status === "open";
        socketOpenRef.current = open;
        if (open && readyWaitersRef.current.length) {
          const waiters = readyWaitersRef.current;
          readyWaitersRef.current = [];
          waiters.forEach((resolve) => resolve());
        }
      },
      onMessage: (data) => {
        if (!acceptingRef.current) return;
        const frame = data as { type?: string; text?: string };
        if (frame.type === "chunk" && typeof frame.text === "string") {
          setStreaming((prev) => (prev ?? "") + frame.text);
        }
      },
    });
    return () => {
      socket.close();
      socketOpenRef.current = false;
    };
  }, [conversationId]);

  const start = useCallback(async () => {
    if (!competitionId || startingRef.current) return;
    startingRef.current = true;
    setStarting(true);
    setError(null);
    try {
      const conv = await aiApi.createConversation(competitionId);
      setMessages([]);
      setClosed(false);
      conversationIdRef.current = conv.id;
      setConversationId(conv.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      startingRef.current = false;
      setStarting(false);
    }
  }, [competitionId]);

  // Open a conversation lazily — called when the panel is first shown, so staff
  // who never open the assistant leave no conversation row. A no-op once one
  // exists (or is being created), so reopening the panel resumes the thread. The
  // ref reads gate synchronous double-invocation (a create is not idempotent).
  const ensureStarted = useCallback(() => {
    if (!conversationIdRef.current && !startingRef.current) void start();
  }, [start]);

  /** Resolve once the socket is authed (driven by its onStatus event, not a
   *  poll), or after a short grace period — a turn posted before the room is
   *  joined would miss its opening chunks (the answer still arrives whole via
   *  the POST response, just not live). */
  const waitForSocket = useCallback((timeoutMs = 4000): Promise<void> => {
    if (socketOpenRef.current) return Promise.resolve();
    return new Promise((resolve) => {
      let settled = false;
      const done = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve();
      };
      const timer = setTimeout(done, timeoutMs);
      readyWaitersRef.current.push(done);
    });
  }, []);

  const send = useCallback(
    async (raw: string) => {
      const content = raw.trim();
      const convId = conversationId;
      if (!content || !competitionId || !convId || sendingRef.current || closed) return;
      sendingRef.current = true;
      setError(null);
      setSending(true);
      seqRef.current += 1;
      setMessages((m) => [
        ...m,
        { id: `u-${seqRef.current}`, role: "user", content },
      ]);
      await waitForSocket();
      // A startNew() during the wait would have swapped the conversation — don't
      // post this message into the old one (its reply would land in the new
      // thread's transcript).
      if (conversationIdRef.current !== convId) {
        sendingRef.current = false;
        setSending(false);
        return;
      }
      setStreaming("");
      acceptingRef.current = true;
      try {
        const msg = await aiApi.postMessage(competitionId, convId, content);
        setMessages((m) => [
          ...m,
          { id: msg.id, role: "assistant", content: msg.content },
        ]);
        // Refresh the token-usage indicator so the "surprise bill" guard
        // reflects the turn that just completed.
        void queryClient.invalidateQueries({
          queryKey: ["ai", "usage", competitionId],
        });
      } catch (e) {
        const err = e as ApiError;
        // 409 → the conversation is full or already closed; a fresh one is the
        // only way forward, so surface that rather than a bare error.
        if (err.status === 409) setClosed(true);
        setError(err.message);
      } finally {
        acceptingRef.current = false;
        setStreaming(null);
        sendingRef.current = false;
        setSending(false);
      }
    },
    [competitionId, conversationId, closed, waitForSocket, queryClient],
  );

  return {
    messages,
    streaming,
    sending,
    starting,
    error,
    closed,
    ready: Boolean(conversationId),
    send,
    /** Create the conversation if there isn't one yet (idempotent). */
    ensureStarted,
    /** Open a fresh conversation — used both to retry a failed create and to
     *  start over after the length cap closes one. */
    startNew: start,
  };
}
