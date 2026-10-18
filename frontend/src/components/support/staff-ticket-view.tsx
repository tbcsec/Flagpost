"use client";

import { useEffect, useRef, useState } from "react";

import { useTranslations } from "next-intl";
import dynamic from "next/dynamic";

import { PresenceIndicator } from "@/components/presence/presence-indicator";
import { ScreenshotPicker } from "@/components/support/screenshot-picker";
import { TicketMessageList } from "@/components/support/ticket-message-list";
import { type SendMode, useTicketSend } from "@/components/support/use-ticket-send";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { useAccess } from "@/lib/hooks/use-permissions";
import { usePresence } from "@/lib/hooks/use-presence";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import { useAssignTicket, useResolveTicket, useTicket } from "@/lib/hooks/use-tickets";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

// The staff notes pad pulls TipTap + Y.js — load it only when the Staff notes
// tab is opened, not with the rest of the support view.
const CollabNote = dynamic(
  () => import("@/components/collab/collab-note").then((m) => m.CollabNote),
  { ssr: false, loading: () => <Skeleton className="h-32 w-full" /> },
);

// One ticket, as staff work it (#503). The ticket's details and its actions
// (assign, resolve) sit apart from writing a message, and the message's kind —
// a reply the competitor reads, an internal note only staff see, or an answer
// posted to everyone as a clarification (#450) — is chosen explicitly and
// changes how the composer looks before anything is sent. Live over the
// ticket's WS room, like the competitor's thread.
export function StaffTicketView({
  competitionId,
  ticketId,
}: {
  competitionId: string;
  ticketId: string;
}) {
  const ticket = useTicket(competitionId, ticketId);
  const sender = useTicketSend(competitionId, ticketId);
  const assign = useAssignTicket(competitionId, ticketId);
  const resolve = useResolveTicket(competitionId, ticketId);
  const presence = usePresence("ticket", ticketId);
  const access = useAccess();
  const userId = useAuthStore((s) => s.user?.id);
  const tr = useTranslations("support");
  const ts = useTranslations("support.staff");
  const rel = useRelativeTime();

  const [tab, setTab] = useState<"conversation" | "notes">("conversation");
  const [mode, setMode] = useState<SendMode>("reply");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  // The question as everyone will read it, seeded from the asker's message for
  // the judge to strip anything identifying.
  const [question, setQuestion] = useState("");
  // Opening a ticket moves focus to it — on a phone the queue row that had
  // focus is hidden, and anywhere it tells a screen reader where they are.
  const headingRef = useRef<HTMLHeadingElement>(null);
  const loaded = Boolean(ticket.data);
  useEffect(() => {
    if (loaded) headingRef.current?.focus();
  }, [loaded]);

  const t = ticket.data;
  // Only when there's nothing to show: a failed background refetch keeps the
  // ticket that's already on screen.
  if (ticket.isError && !t) {
    return <p className="text-sm text-muted-foreground">{ts("notFound")}</p>;
  }
  if (!t) return <Skeleton className="h-96 w-full" />;

  const isQuestion = t.kind === "question";
  const aboutChallenge = Boolean(t.challenge_id);
  const canSendToAll = aboutChallenge && access.has("announcement_create");
  const assignedToMe = Boolean(userId) && t.assignee_user_id === userId;
  const attachedCount = t.messages.reduce((n, m) => n + m.attachments.length, 0);

  const modes: { value: SendMode; label: string }[] = [
    { value: "reply", label: isQuestion ? ts("mode.answer") : ts("mode.reply") },
    { value: "internal", label: ts("mode.internal") },
    ...(canSendToAll ? [{ value: "everyone" as const, label: ts("mode.everyone") }] : []),
  ];

  function chooseMode(next: SendMode) {
    setMode(next);
    if (next === "everyone") {
      setFiles([]);
      if (!question) setQuestion(t?.messages[0]?.body ?? "");
    }
  }

  function onSend(e: React.FormEvent) {
    e.preventDefault();
    sender.send(
      // Screenshots go with a reply or an internal note; a clarification is text.
      { mode, body, files: mode === "everyone" ? [] : files, question },
      {
        onSent: () => {
          setBody("");
          setFiles([]);
          setQuestion("");
          setMode("reply");
        },
      },
    );
  }

  const sendLabel = sender.sending
    ? tr("thread.sending")
    : mode === "everyone"
      ? tr("thread.sendToAll")
      : mode === "internal"
        ? ts("sendInternal")
        : isQuestion
          ? tr("thread.sendAnswer")
          : tr("thread.send");
  // Only the opener sees a ticket (teammates don't), so a reply reaches them.
  const hint =
    mode === "internal"
      ? ts("mode.internalHint")
      : mode === "everyone"
        ? tr("thread.toAllHint")
        : ts("mode.replyHint", { name: t.opener_name });
  const modeLabel = modes.find((m) => m.value === mode)?.label ?? "";
  const hintId = `ticket-${t.id}-mode-hint`;

  return (
    <article className="grid gap-4" aria-labelledby={`ticket-${t.id}-subject`}>
      <header className="grid gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              {isQuestion && (
                <span className="rounded-full bg-primary/10 px-2 py-px text-[11px] font-medium text-primary">
                  {tr("questionTag")}
                </span>
              )}
              <Badge variant={t.status === "open" ? "destructive" : "muted"}>
                {isQuestion ? tr(`questionStatus.${t.status}`) : tr(`status.${t.status}`)}
              </Badge>
              {t.awaiting_staff && <Badge variant="warning">{ts("waiting")}</Badge>}
            </div>
            <h2
              id={`ticket-${t.id}-subject`}
              ref={headingRef}
              tabIndex={-1}
              className="mt-1.5 font-display text-lg font-semibold tracking-tight [overflow-wrap:anywhere] focus:outline-none"
            >
              {t.subject}
            </h2>
          </div>
          {/* Ticket actions — about the ticket, not the message being written. */}
          <div className="flex shrink-0 items-center gap-2">
            {assignedToMe ? (
              <span className="text-xs text-muted-foreground">{ts("assignedToYou")}</span>
            ) : (
              <Button
                variant="outline"
                size="sm"
                disabled={assign.isPending}
                onClick={() =>
                  assign.mutate(undefined, { onSuccess: () => toast(tr("thread.assignedToast")) })
                }
              >
                {tr("thread.assignToMe")}
              </Button>
            )}
            {t.status === "open" && (
              <Button
                variant="outline"
                size="sm"
                disabled={resolve.isPending}
                onClick={() =>
                  resolve.mutate(undefined, {
                    onSuccess: () => toast(tr("thread.resolvedToast"), { variant: "success" }),
                  })
                }
              >
                {tr("thread.resolve")}
              </Button>
            )}
          </div>
        </div>
        <dl className="grid grid-cols-[repeat(auto-fill,minmax(10rem,1fr))] gap-x-4 gap-y-2 rounded-md border border-border bg-muted/30 px-3 py-2.5 text-sm">
          <Detail label={ts("detail.from")} value={t.team_name ? `${t.team_name} · ${t.opener_name}` : t.opener_name} />
          {t.challenge_title && <Detail label={ts("detail.challenge")} value={t.challenge_title} />}
          <Detail label={ts("detail.assignee")} value={t.assignee_name ?? ts("unassigned")} />
          <Detail label={ts("detail.opened")} value={rel(t.created_at)} />
          {t.last_activity_at && <Detail label={ts("detail.lastActivity")} value={rel(t.last_activity_at)} />}
        </dl>
      </header>

      {presence.others.length > 0 && (
        <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/40 px-3 py-2">
          <span className="text-xs text-muted-foreground">
            {tr("thread.othersHere", { count: presence.others.length })}
          </span>
          <PresenceIndicator members={presence.others} max={5} />
        </div>
      )}

      <Tabs
        tabs={[
          { value: "conversation", label: ts("tabs.conversation") },
          { value: "notes", label: ts("tabs.notes") },
        ]}
        value={tab}
        onValueChange={(v) => setTab(v as "conversation" | "notes")}
      />

      {tab === "notes" ? (
        <section className="grid gap-2">
          <p className="text-xs text-muted-foreground">{tr("thread.staffNotesDesc")}</p>
          <CollabNote docKey={`ticket:${ticketId}`} />
        </section>
      ) : (
        <>
          <TicketMessageList
            competitionId={competitionId}
            ticketId={ticketId}
            messages={t.messages}
            // Staff may remove any attachment (moderation) — the API's rule too.
            canDelete={() => true}
          />

          <form
            onSubmit={onSend}
            className={cn(
              "grid gap-2.5 rounded-lg border p-3",
              mode === "internal" && "border-warning/50 bg-warning/5",
              mode === "everyone" && "border-primary/50 bg-primary/5",
              mode === "reply" && "border-border",
            )}
          >
            {/* Native radios (one tab stop, arrow keys), drawn as pills. */}
            <fieldset className="flex flex-wrap gap-1.5">
              <legend className="sr-only">{ts("mode.label")}</legend>
              {modes.map((m) => (
                <label
                  key={m.value}
                  className={cn(
                    "cursor-pointer rounded-full border px-3 py-1 text-xs font-medium transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-background",
                    mode === m.value
                      ? "border-foreground bg-foreground text-background"
                      : "border-border text-muted-foreground hover:text-foreground",
                  )}
                >
                  <input
                    type="radio"
                    name={`ticket-${t.id}-mode`}
                    value={m.value}
                    checked={mode === m.value}
                    onChange={() => chooseMode(m.value)}
                    className="sr-only"
                  />
                  {m.label}
                </label>
              ))}
            </fieldset>
            <p id={hintId} className="text-xs text-muted-foreground">{hint}</p>

            {aboutChallenge && mode !== "internal" && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-muted-foreground">{tr("thread.quickAnswers")}</span>
                {(["noComment", "readStatement"] as const).map((key) => (
                  <Button
                    key={key}
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={() => setBody(tr(`thread.quick.${key}`))}
                  >
                    {tr(`thread.quickLabel.${key}`)}
                  </Button>
                ))}
              </div>
            )}

            {mode === "everyone" && (
              <div className="grid gap-1.5">
                <label htmlFor={`clarify-question-${ticketId}`} className="text-[13px] font-medium">
                  {tr("thread.toAllQuestion")}
                </label>
                <textarea
                  id={`clarify-question-${ticketId}`}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  required
                  rows={2}
                  className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                />
              </div>
            )}

            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              required
              rows={3}
              aria-label={modeLabel}
              aria-describedby={hintId}
              placeholder={
                mode === "internal"
                  ? ts("internalPlaceholder")
                  : isQuestion || mode === "everyone"
                    ? tr("thread.answerPlaceholder")
                    : tr("thread.replyPlaceholder")
              }
              className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            />
            {/* Screenshots go with a reply or an internal note on an ordinary
                ticket: a question is text both ways (#450), and a
                clarification is text. */}
            {mode !== "everyone" && !isQuestion && (
              <ScreenshotPicker
                files={files}
                onChange={setFiles}
                existingCount={attachedCount}
                disabled={sender.sending}
              />
            )}
            <div className="flex justify-end">
              <Button type="submit" size="sm" disabled={sender.sending}>
                {sendLabel}
              </Button>
            </div>
            {sender.error && (
              <p role="alert" className="text-sm text-destructive">{sender.error.message}</p>
            )}
          </form>
        </>
      )}
    </article>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="truncate">{value}</dd>
    </div>
  );
}
