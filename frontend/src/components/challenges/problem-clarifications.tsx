"use client";

// Questions about a problem and the judges' clarifications (#450), as the
// closing part of the statement itself (owner decision: not a separate box) —
// a clarification amends the statement, so it reads with it. A competitor asks
// privately (a support ticket linked to the problem, which only staff see) and
// reads every clarification the judges sent to everyone, newest first. Quiet
// by design: with nothing to show it's one line.

import { useTranslations } from "next-intl";
import { useState } from "react";

import { TicketThread } from "@/components/support/ticket-thread";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { useClarifications } from "@/lib/hooks/use-announcements";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import { useCreateTicket, useTickets } from "@/lib/hooks/use-tickets";
import { toast } from "@/stores/toast";

const TEXTAREA =
  "flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

// A text-weight action, not a boxed button.
const INLINE_ACTION =
  "rounded-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

const CLARIFICATIONS_ANCHOR = "clarifications";

const speechIcon = (
  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);

const helpIcon = (
  <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
    <path d="M12 17h.01" />
  </svg>
);

/** "· 2 clarifications" for the problem's info line, jumping to them — so a
 *  competitor notices the statement was amended without scrolling. */
export function ClarificationsLink({
  competitionId,
  challengeId,
}: {
  competitionId: string;
  challengeId: string;
}) {
  const t = useTranslations("challenges.code.clarifications");
  const count = useClarifications(competitionId, challengeId).data?.length ?? 0;
  if (count === 0) return null;
  return (
    <>
      {" · "}
      <a href={`#${CLARIFICATIONS_ANCHOR}`} className={INLINE_ACTION}>
        {t("count", { count })}
      </a>
    </>
  );
}

export function ProblemClarifications({
  competitionId,
  challengeId,
  challengeTitle,
}: {
  competitionId: string;
  challengeId: string;
  challengeTitle: string;
}) {
  const t = useTranslations("challenges.code.clarifications");
  const access = useAccess();
  const rel = useRelativeTime();
  // Staff answer questions on the Support page; asking is for competitors.
  const canAsk = access.has("ticket_respond") && !access.has("ticket_assign");
  const clarifications = useClarifications(competitionId, challengeId);
  const tickets = useTickets(competitionId, undefined, { enabled: canAsk });
  const [asking, setAsking] = useState(false);
  const [showMine, setShowMine] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  const items = clarifications.data ?? [];
  const mine = canAsk
    ? (tickets.data ?? []).filter((x) => x.kind === "question" && x.challenge_id === challengeId)
    : [];

  if (items.length === 0 && !canAsk) return null;

  return (
    <section
      id={CLARIFICATIONS_ANCHOR}
      aria-label={t("title")}
      className="mt-6 scroll-mt-6 space-y-4 border-t border-border pt-4"
    >
      {items.length > 0 && (
        <div className="space-y-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <span className="text-primary">{speechIcon}</span>
            {t("title")}
            <span className="font-normal text-muted-foreground">· {items.length}</span>
          </h2>
          <ul className="space-y-2">
            {items.map((c) => (
              // A callout per clarification: it amends the statement, so it
              // should stand out from it.
              <li
                key={c.id}
                className="space-y-1 rounded-md border-l-2 border-primary bg-primary/5 px-3 py-2"
              >
                {c.question && (
                  <p className="flex gap-2 text-sm text-muted-foreground">
                    <span aria-hidden="true" className="w-4 shrink-0 font-semibold">
                      {t("q")}
                    </span>
                    <span className="sr-only">{t("questionSr")}</span>
                    <span className="min-w-0 whitespace-pre-line">{c.question}</span>
                  </p>
                )}
                <p className="flex gap-2 text-sm text-foreground">
                  <span aria-hidden="true" className="w-4 shrink-0 font-semibold text-primary">
                    {t("a")}
                  </span>
                  <span className="sr-only">{t("answerSr")}</span>
                  <span className="min-w-0 flex-1 whitespace-pre-line">{c.body}</span>
                  <span className="shrink-0 self-end whitespace-nowrap text-[11px] text-muted-foreground">
                    {rel(c.created_at)}
                  </span>
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {canAsk && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md bg-muted/50 px-3 py-2.5">
            <span className="text-muted-foreground">{helpIcon}</span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{t("askPrompt")}</p>
              <p className="text-xs text-muted-foreground">{t("askPrivacy")}</p>
            </div>
            {mine.length > 0 && (
              <button
                type="button"
                className={INLINE_ACTION + " text-sm"}
                aria-expanded={showMine}
                onClick={() => setShowMine((v) => !v)}
              >
                {t("yourQuestions", { count: mine.length })}
              </button>
            )}
            <Button type="button" variant="outline" size="sm" onClick={() => setAsking(true)}>
              {t("ask")}
            </Button>
          </div>
          {showMine && mine.length > 0 && (
            <ul className="divide-y divide-border rounded-md border border-border">
              {mine.map((q) => (
                <li key={q.id}>
                  <button
                    type="button"
                    onClick={() => setOpenId(q.id)}
                    className="flex w-full flex-wrap items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent/60"
                  >
                    <span className="flex-1">{t("yourQuestion", { time: rel(q.created_at) })}</span>
                    <span className="text-xs text-muted-foreground">
                      {t("messages", { count: q.message_count })}
                    </span>
                    <Badge variant={q.status === "open" ? "outline" : "success"}>
                      {q.status === "open" ? t("statusWaiting") : t("statusAnswered")}
                    </Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {asking && (
        <AskDialog
          competitionId={competitionId}
          challengeId={challengeId}
          challengeTitle={challengeTitle}
          onClose={() => setAsking(false)}
          onAsked={(id) => {
            setAsking(false);
            setOpenId(id);
          }}
        />
      )}
      <Dialog open={!!openId} onOpenChange={(o) => !o && setOpenId(null)}>
        <DialogContent>
          {openId && (
            <TicketThread
              competitionId={competitionId}
              ticketId={openId}
              isStaff={false}
              onAskAgain={() => {
                setOpenId(null);
                setAsking(true);
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}

function AskDialog({
  competitionId,
  challengeId,
  challengeTitle,
  onClose,
  onAsked,
}: {
  competitionId: string;
  challengeId: string;
  challengeTitle: string;
  onClose: () => void;
  onAsked: (ticketId: string) => void;
}) {
  const t = useTranslations("challenges.code.clarifications");
  const create = useCreateTicket(competitionId);
  const [body, setBody] = useState("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      {
        // A ticket needs a subject; this one says what the question is about.
        subject: t("subject", { title: challengeTitle }).slice(0, 200),
        body,
        challenge_id: challengeId,
        kind: "question",
      },
      {
        onSuccess: (ticket) => {
          toast(t("askedToast"), { variant: "success" });
          onAsked(ticket.id);
        },
      },
    );
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{t("askTitle")}</DialogTitle>
            <DialogDescription>{t("askDescription")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="ask-question">{t("questionLabel")}</Label>
            <textarea
              id="ask-question"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              required
              maxLength={5000}
              rows={5}
              placeholder={t("questionPlaceholder")}
              className={TEXTAREA}
            />
          </div>
          {create.isError && (
            <p role="alert" className="text-sm text-destructive">
              {(create.error as Error).message}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={create.isPending || !body.trim()}>
              {create.isPending ? t("sending") : t("send")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
