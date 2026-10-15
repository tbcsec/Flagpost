"use client";

// Questions about a challenge and the judges' clarifications (#450), as the
// closing part of the statement itself (owner decision: not a separate box) —
// a clarification amends the statement, so it reads with it. A competitor asks
// privately (a support ticket linked to the challenge, which only staff see)
// and reads every clarification the judges sent to everyone, newest first.
// Staff can also post one themselves and withdraw one. Used on the
// programming problem page and, without asking, in a flag challenge's dialog.
// Quiet by design: with nothing to show it's one line.

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
import { useConfirm } from "@/components/ui/confirm";
import { Label } from "@/components/ui/label";
import {
  useClarifications,
  usePostClarification,
  useWithdrawClarification,
} from "@/lib/hooks/use-announcements";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useRelativeTime } from "@/lib/hooks/use-relative-time";
import { useCreateTicket, useTickets } from "@/lib/hooks/use-tickets";
import { cn } from "@/lib/utils";
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
  // Only the ones in force: a withdrawn clarification amends nothing.
  const count = (useClarifications(competitionId, challengeId).data ?? []).filter(
    (c) => !c.withdrawn_at,
  ).length;
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
  allowAsk = true,
}: {
  competitionId: string;
  challengeId: string;
  challengeTitle: string;
  /** Offer "Ask the judges" (the programming problem page). A flag
   *  challenge's dialog shows clarifications only (owner decision). */
  allowAsk?: boolean;
}) {
  const t = useTranslations("challenges.code.clarifications");
  const access = useAccess();
  const rel = useRelativeTime();
  const confirm = useConfirm();
  // Staff answer questions on the Support page; asking is for competitors.
  const canAsk = allowAsk && access.has("ticket_respond") && !access.has("ticket_assign");
  // Staff post a clarification of their own (a statement fix, say) and can
  // take one back (#450 follow-ups).
  const canPost = access.has("announcement_create");
  const canWithdraw = access.has("announcement_delete");
  const clarifications = useClarifications(competitionId, challengeId);
  const withdraw = useWithdrawClarification(competitionId, challengeId);
  const [posting, setPosting] = useState(false);
  const tickets = useTickets(competitionId, undefined, { enabled: canAsk });
  const [asking, setAsking] = useState(false);
  const [showMine, setShowMine] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  const items = clarifications.data ?? [];
  const mine = canAsk
    ? (tickets.data ?? []).filter((x) => x.kind === "question" && x.challenge_id === challengeId)
    : [];

  if (items.length === 0 && !canAsk && !canPost) return null;

  return (
    <section
      id={CLARIFICATIONS_ANCHOR}
      aria-label={t("title")}
      className="mt-6 scroll-mt-6 space-y-4 border-t border-border pt-4"
    >
      {(items.length > 0 || canPost) && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <span className="text-primary">{speechIcon}</span>
              {t("title")}
              {items.length > 0 && (
                <span className="font-normal text-muted-foreground">· {items.length}</span>
              )}
            </h2>
            {canPost && (
              <Button type="button" variant="outline" size="sm" onClick={() => setPosting(true)}>
                {t("post")}
              </Button>
            )}
          </div>
          {items.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("staffEmpty")}</p>
          )}
          <ul className="space-y-2">
            {items.map((c) => {
              const withdrawn = Boolean(c.withdrawn_at);
              return (
                // A callout per clarification: it amends the statement, so it
                // should stand out from it — unless withdrawn, when it stays
                // (so readers know not to rely on it) but recedes.
                <li
                  key={c.id}
                  className={cn(
                    "space-y-1 rounded-md border-l-2 px-3 py-2",
                    withdrawn ? "border-border bg-muted/40 opacity-75" : "border-primary bg-primary/5",
                  )}
                >
                  {withdrawn && (
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {t("withdrawn")}
                    </p>
                  )}
                  {c.question && (
                    <p className="flex gap-2 text-sm text-muted-foreground">
                      <span aria-hidden="true" className="w-4 shrink-0 font-semibold">
                        {t("q")}
                      </span>
                      <span className="sr-only">{t("questionSr")}</span>
                      <span className="min-w-0 whitespace-pre-line">{c.question}</span>
                    </p>
                  )}
                  {/* A competitor gets no answer once withdrawn; staff keep
                      theirs, struck through. */}
                  {(c.body || !withdrawn) && (
                    <p
                      className={cn(
                        "flex gap-2 text-sm",
                        withdrawn ? "text-muted-foreground line-through" : "text-foreground",
                      )}
                    >
                      {c.question && (
                        <>
                          <span aria-hidden="true" className="w-4 shrink-0 font-semibold text-primary">
                            {t("a")}
                          </span>
                          <span className="sr-only">{t("answerSr")}</span>
                        </>
                      )}
                      <span className="min-w-0 flex-1 whitespace-pre-line">{c.body}</span>
                    </p>
                  )}
                  <div className="flex items-center justify-end gap-2">
                    <span className="whitespace-nowrap text-[11px] text-muted-foreground">
                      {rel(c.created_at)}
                    </span>
                    {canWithdraw && !withdrawn && (
                      <button
                        type="button"
                        className="rounded-sm text-[11px] font-medium text-destructive underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        disabled={withdraw.isPending}
                        onClick={async () => {
                          if (
                            await confirm({
                              title: t("withdrawConfirmTitle"),
                              description: t("withdrawConfirmDescription"),
                              confirmLabel: t("withdrawConfirm"),
                            })
                          ) {
                            withdraw.mutate(c.id, {
                              onSuccess: () => toast(t("withdrawnToast"), { variant: "success" }),
                              onError: (e) => toast((e as Error).message, { variant: "destructive" }),
                            });
                          }
                        }}
                      >
                        {t("withdraw")}
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
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

      {posting && (
        <PostDialog
          competitionId={competitionId}
          challengeId={challengeId}
          onClose={() => setPosting(false)}
        />
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

/** Staff: a clarification with no competitor's question behind it — a
 *  statement fix, say. Sent to everyone and shown with the challenge. */
function PostDialog({
  competitionId,
  challengeId,
  onClose,
}: {
  competitionId: string;
  challengeId: string;
  onClose: () => void;
}) {
  const t = useTranslations("challenges.code.clarifications");
  const post = usePostClarification(competitionId, challengeId);
  const [body, setBody] = useState("");
  const [question, setQuestion] = useState("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    post.mutate(
      { body, question: question.trim() || null },
      {
        onSuccess: () => {
          toast(t("postedToast"), { variant: "success" });
          onClose();
        },
      },
    );
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{t("postTitle")}</DialogTitle>
            <DialogDescription>{t("postDescription")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="post-clarification">{t("postBody")}</Label>
            <textarea
              id="post-clarification"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              required
              maxLength={5000}
              rows={4}
              placeholder={t("postBodyPlaceholder")}
              className={TEXTAREA}
            />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="post-clarification-question">{t("postQuestion")}</Label>
            <textarea
              id="post-clarification-question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={5000}
              rows={2}
              className={TEXTAREA}
            />
          </div>
          {post.isError && (
            <p role="alert" className="text-sm text-destructive">
              {(post.error as Error).message}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={post.isPending || !body.trim()}>
              {post.isPending ? t("sending") : t("postSend")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
