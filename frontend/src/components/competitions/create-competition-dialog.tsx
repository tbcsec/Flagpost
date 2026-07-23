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
import { useCreateCompetition } from "@/lib/hooks/use-competitions";
import type { ParticipationMode, Visibility } from "@/lib/types";

// Feature component (§14 components/<domain>). Talks to the domain hook, not
// the API client. RBAC is enforced server-side: a user without
// create_competition gets a 403, surfaced here as an inline error — the UI
// doesn't duplicate the permission check. Detailed schedule / registration
// windows live on the settings page; creation captures the essentials.
export function CreateCompetitionDialog() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState<ParticipationMode>("team");
  const [visibility, setVisibility] = useState<Visibility>("private");
  const create = useCreateCompetition();

  function reset() {
    setName("");
    setDescription("");
    setMode("team");
    setVisibility("private");
    create.reset();
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      {
        name,
        description,
        participation_mode: mode,
        visibility,
      },
      {
        onSuccess: () => {
          reset();
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
            <Label htmlFor="competition-description">Description</Label>
            <Input
              id="competition-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="competition-mode">Participation mode</Label>
              <Select
                id="competition-mode"
                value={mode}
                onChange={(e) => setMode(e.target.value as ParticipationMode)}
              >
                <option value="team">Team</option>
                <option value="individual">Individual</option>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="competition-visibility">Visibility</Label>
              <Select
                id="competition-visibility"
                value={visibility}
                onChange={(e) => setVisibility(e.target.value as Visibility)}
              >
                <option value="private">Private</option>
                <option value="public">Public</option>
              </Select>
            </div>
          </div>
          {create.isError && (
            <p role="alert" className="text-sm text-destructive">
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
