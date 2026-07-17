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
import { useCreateCompetition } from "@/lib/hooks/use-competitions";
import type { ParticipationMode } from "@/lib/types";

// Feature component (§14 components/<domain>). Talks to the domain hook, not
// the API client. RBAC is enforced server-side: a user without
// create_competition gets a 403, surfaced here as an inline error — the UI
// doesn't duplicate the permission check.
export function CreateCompetitionDialog() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [mode, setMode] = useState<ParticipationMode>("team");
  const create = useCreateCompetition();

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      { name, participation_mode: mode },
      {
        onSuccess: () => {
          setName("");
          setMode("team");
          create.reset();
          setOpen(false);
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
        <Button>New competition</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New competition</DialogTitle>
          <DialogDescription>
            Create a competition to scope challenges, teams, and scoring under.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="competition-name">Name</Label>
            <Input
              id="competition-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="competition-mode">Participation mode</Label>
            <select
              id="competition-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as ParticipationMode)}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <option value="team">Team</option>
              <option value="individual">Individual</option>
            </select>
          </div>
          {create.isError && (
            <p className="text-sm text-destructive">
              {(create.error as Error).message}
            </p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
