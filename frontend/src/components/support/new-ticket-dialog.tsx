"use client";

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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useChallenges } from "@/lib/hooks/use-challenges";
import { useCreateTicket } from "@/lib/hooks/use-tickets";
import { toast } from "@/stores/toast";

// A competitor opens a ticket, optionally tied to a challenge. RBAC
// (ticket_respond) is server-enforced; the thread then goes live over the
// ticket's WS room.
export function NewTicketDialog({ competitionId }: { competitionId: string }) {
  const [open, setOpen] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const create = useCreateTicket(competitionId);
  const challenges = useChallenges(competitionId);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      { subject, body, challenge_id: challengeId || null },
      {
        onSuccess: () => {
          setSubject("");
          setBody("");
          setChallengeId("");
          setOpen(false);
          toast("Ticket opened", { variant: "success" });
        },
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) create.reset();
      }}
    >
      <DialogTrigger asChild>
        <Button>New ticket</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New ticket</DialogTitle>
          <DialogDescription>Ask a question — staff will see it and reply.</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="ticket-subject">Subject</Label>
            <Input id="ticket-subject" value={subject} onChange={(e) => setSubject(e.target.value)} required />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="ticket-challenge">Related challenge (optional)</Label>
            <Select
              id="ticket-challenge"
              value={challengeId}
              onChange={(e) => setChallengeId(e.target.value)}
            >
              <option value="">None</option>
              {challenges.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </Select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="ticket-body">Message</Label>
            <textarea
              id="ticket-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              required
              rows={4}
              className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            />
          </div>
          {create.isError && (
            <p role="alert" className="text-sm text-destructive">{(create.error as Error).message}</p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Opening…" : "Open ticket"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
