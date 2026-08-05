"use client";

// The administrator-assistant chat (#98, ADR-0023, Phase 2) — an understated,
// audience-aware launcher docked in the app shell that opens a side panel and
// streams answers over the `ai` WS room. Read-only: every tool the assistant
// calls re-checks the viewer's permissions, so it can only surface what the
// organiser could already see.
//
// Mounting is decided by <AiAssistantMount>: a client-side staff check gates the
// availability request (so a competitor never fires it), and the request's
// answer — which also confirms the module is configured + enabled here — gates
// the launcher itself.

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useAiAvailability, useAiChat, useAiUsage } from "@/lib/hooks/use-ai";
import { cn } from "@/lib/utils";

// The staff-marker permissions that make a user staff enough for the admin
// assistant — kept in step with the backend's `_STAFF_MARKER_PERMISSIONS`
// (utils/ai/tools.py). Used only to avoid firing the availability request for a
// bare participant; the server re-decides authoritatively.
const STAFF_MARKERS = [
  "view_competition_analytics",
  "ticket_assign",
  "feedback_view_responses",
  "announcement_create",
];

const SUGGESTIONS = [
  "How is the competition going so far?",
  "Are there any open support tickets?",
  "Which challenges are the hardest right now?",
];

const sparkIcon = (
  <svg
    width="18"
    height="18"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
    <path d="M12 8.5 13.2 11 15.5 12l-2.3 1-1.2 2.5L10.8 13 8.5 12l2.3-1L12 8.5z" />
  </svg>
);

export function AiAssistantMount({
  competitionId,
  competitionName,
}: {
  competitionId: string;
  competitionName?: string;
}) {
  const access = useAccess();
  const canUse = STAFF_MARKERS.some((k) => access.has(k));
  const availability = useAiAvailability(competitionId, access.ready && canUse);
  if (!availability.data?.available) return null;
  return (
    <AiAssistant
      // Fresh chat state per competition — keying drops a stale thread when the
      // active competition changes.
      key={competitionId}
      competitionId={competitionId}
      competitionName={competitionName}
    />
  );
}

function AiAssistant({
  competitionId,
  competitionName,
}: {
  competitionId: string;
  competitionName?: string;
}) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [input, setInput] = useState("");

  const chat = useAiChat(competitionId);
  const usage = useAiUsage(competitionId, open);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Keep the transcript pinned to the newest content as it streams in.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat.messages, chat.streaming, chat.error, chat.closed]);

  // Focus the composer once the conversation is ready and the panel is open.
  useEffect(() => {
    if (open && chat.ready) inputRef.current?.focus();
  }, [open, chat.ready]);

  const composerDisabled = !chat.ready || chat.sending || chat.closed;

  function submit(text: string) {
    const value = text.trim();
    if (!value || composerDisabled) return;
    setInput("");
    void chat.send(value);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit(input);
    }
  }

  const usageText =
    usage.data && usage.data.message_count > 0
      ? `${(usage.data.input_tokens + usage.data.output_tokens).toLocaleString()} tokens`
      : null;

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          setOpen(true);
          chat.ensureStarted();
        }}
        aria-label="Open the organiser assistant"
        className="fixed bottom-4 right-4 z-[90] flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg outline-none transition-transform hover:scale-105 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        {sparkIcon}
      </button>
    );
  }

  return (
    <div
      role="dialog"
      aria-label="Organiser assistant"
      className={cn(
        "fixed z-[90] flex flex-col overflow-hidden rounded-xl border border-border bg-card shadow-2xl",
        // Mobile: fill most of the screen. sm+: dock bottom-right.
        "inset-x-3 bottom-3 top-16 sm:inset-x-auto sm:bottom-4 sm:right-4 sm:top-auto",
        expanded
          ? "sm:h-[85vh] sm:w-[720px] sm:max-w-[92vw]"
          : "sm:h-[34rem] sm:w-[26rem]",
      )}
    >
      <header className="flex items-center gap-2 border-b border-border px-4 py-3">
        <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
          {sparkIcon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold leading-tight">Organiser assistant</div>
          <div className="truncate text-xs text-muted-foreground">
            {competitionName ? `${competitionName} · read-only` : "Read-only"}
          </div>
        </div>
        {usageText && (
          <span
            className="hidden text-[11px] text-muted-foreground sm:inline"
            title="Tokens spent by the assistant in this competition"
          >
            {usageText}
          </span>
        )}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-label={expanded ? "Shrink the assistant" : "Expand the assistant"}
          className="hidden rounded-md p-1.5 text-muted-foreground hover:bg-accent/60 hover:text-foreground sm:block"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            {expanded ? (
              <path d="M9 3H3v6M21 15v6h-6M3 3l7 7M21 21l-7-7" />
            ) : (
              <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
            )}
          </svg>
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Close the assistant"
          className="rounded-md p-1.5 text-muted-foreground hover:bg-accent/60 hover:text-foreground"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </header>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {chat.messages.length === 0 && chat.streaming === null && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Ask about standings, tickets, challenge stats, feedback or
              announcements. I only read — I can&apos;t change anything — and I
              answer from what you&apos;re allowed to see.
            </p>
            {chat.ready && !chat.closed && (
              <div className="flex flex-col items-start gap-1.5">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => submit(s)}
                    className="rounded-full border border-border px-3 py-1 text-left text-xs text-foreground transition-colors hover:bg-accent/60"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {chat.messages.map((m) => (
          <MessageBubble key={m.id} role={m.role} content={m.content} />
        ))}

        {chat.streaming !== null && (
          <MessageBubble role="assistant" content={chat.streaming} pending />
        )}

        {chat.error && chat.ready && (
          <p className="text-xs text-destructive">{chat.error}</p>
        )}

        {chat.closed && (
          <div className="rounded-md border border-border bg-muted/40 p-3 text-xs">
            <p className="text-muted-foreground">
              This conversation has reached its length limit.
            </p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="mt-2"
              onClick={() => chat.startNew()}
            >
              Start a new chat
            </Button>
          </div>
        )}
      </div>

      <div className="border-t border-border p-3">
        {!chat.ready && chat.error ? (
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>Couldn&apos;t start the assistant.</span>
            <Button type="button" size="sm" variant="outline" onClick={() => chat.startNew()}>
              Try again
            </Button>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit(input);
            }}
            className="flex items-end gap-2"
          >
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
              maxLength={8000}
              disabled={composerDisabled}
              placeholder={
                chat.ready
                  ? "Ask the assistant…"
                  : chat.starting
                    ? "Connecting…"
                    : "Starting…"
              }
              className="max-h-32 min-h-[2.5rem] flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            />
            <Button
              type="submit"
              size="sm"
              disabled={composerDisabled || !input.trim()}
              className="h-10 flex-shrink-0"
            >
              {chat.sending ? "…" : "Send"}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}

function MessageBubble({
  role,
  content,
  pending,
}: {
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
}) {
  const isUser = role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2 text-sm",
          isUser
            ? "rounded-br-sm bg-primary text-primary-foreground"
            : "rounded-bl-sm bg-muted text-foreground",
        )}
      >
        {content}
        {pending && (content ? <BlinkingCursor /> : <TypingDots />)}
      </div>
    </div>
  );
}

function BlinkingCursor() {
  return <span className="ml-0.5 inline-block animate-pulse">▍</span>;
}

function TypingDots() {
  return (
    <span className="inline-flex gap-1 py-1" aria-label="Assistant is thinking">
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.3s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:-0.15s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground" />
    </span>
  );
}
