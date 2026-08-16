"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ScreenshotPicker } from "@/components/support/screenshot-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useChallenges } from "@/lib/hooks/use-challenges";
import { useCreateTicket, useUploadTicketAttachment } from "@/lib/hooks/use-tickets";
import { toast } from "@/stores/toast";

// A competitor opens a ticket, optionally tied to a challenge. RBAC
// (ticket_respond) is server-enforced; the thread then goes live over the
// ticket's WS room.
export function NewTicketDialog({ competitionId }: { competitionId: string }) {
  const t = useTranslations("support.new");
  const [open, setOpen] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const create = useCreateTicket(competitionId);
  const upload = useUploadTicketAttachment(competitionId);
  const challenges = useChallenges(competitionId);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      { subject, body, challenge_id: challengeId || null },
      {
        onSuccess: async (ticket) => {
          // The message has to exist before anything can attach to it, so the
          // screenshots follow the ticket rather than riding along with it.
          const messageId = ticket.messages[0]?.id;
          // No message to attach to means the screenshots are lost — report it
          // rather than closing on a bare success toast.
          const failures: string[] = messageId ? [] : files.map((f) => f.name);
          if (messageId) {
            for (const file of files) {
              try {
                await upload.mutateAsync({ ticketId: ticket.id, messageId, file });
              } catch {
                failures.push(file.name);
              }
            }
          }
          setSubject("");
          setBody("");
          setChallengeId("");
          setFiles([]);
          setOpen(false);
          // The ticket itself did open — say so, but don't claim the
          // screenshots made it if they didn't.
          if (failures.length > 0) {
            toast(t("openedPartialToast", { files: failures.join(", ") }), {
              variant: "destructive",
            });
          } else {
            toast(t("openedToast"), { variant: "success" });
          }
        },
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          create.reset();
          setFiles([]);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button>{t("trigger")}</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="ticket-subject">{t("subject")}</Label>
            <Input id="ticket-subject" value={subject} onChange={(e) => setSubject(e.target.value)} required />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="ticket-challenge">{t("challenge")}</Label>
            <Select
              id="ticket-challenge"
              value={challengeId}
              onChange={(e) => setChallengeId(e.target.value)}
            >
              <option value="">{t("challengeNone")}</option>
              {challenges.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="ticket-body">{t("message")}</Label>
            <textarea
              id="ticket-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              required
              rows={4}
              className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            />
          </div>
          <div className="grid gap-2">
            <Label>{t("screenshots")}</Label>
            <ScreenshotPicker
              files={files}
              onChange={setFiles}
              disabled={create.isPending || upload.isPending}
            />
          </div>
          {create.isError && (
            <p role="alert" className="text-sm text-destructive">{(create.error as Error).message}</p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={create.isPending || upload.isPending}>
              {create.isPending || upload.isPending ? t("opening") : t("submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
