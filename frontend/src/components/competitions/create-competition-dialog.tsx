"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
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
import { useModuleCatalog } from "@/lib/hooks/use-modules";
import type { ParticipationMode, Visibility } from "@/lib/types";

// Feature component (§14 components/<domain>). Talks to the domain hook, not
// the API client. RBAC is enforced server-side: a user without
// create_competition gets a 403, surfaced here as an inline error — the UI
// doesn't duplicate the permission check.
//
// The onboarding creation surface (#252): beyond the essentials, it captures a
// public-scoreboard toggle, an optional schedule, and which optional modules to
// switch off — so a new competition is usable without an immediate detour into
// settings. Everything richer (registration window, brackets, rules) still
// lives on the settings page.

// datetime-local value -> stored ISO. The input is treated as UTC, matching the
// settings form's convention so the two round-trip identically.
const fromInput = (v: string) => (v ? new Date(`${v}Z`).toISOString() : null);

const CHECKBOX = "h-4 w-4 rounded border-border";
const CHECKBOX_STYLE = { accentColor: "hsl(var(--primary))" } as const;

export function CreateCompetitionDialog() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState<ParticipationMode>("team");
  const [visibility, setVisibility] = useState<Visibility>("private");
  const [publicScoreboard, setPublicScoreboard] = useState(false);
  const [startAt, setStartAt] = useState("");
  const [endAt, setEndAt] = useState("");
  // Optional modules default on, so we track only the ones switched *off*.
  const [disabledModules, setDisabledModules] = useState<Set<string>>(new Set());
  const create = useCreateCompetition();
  // Only fetch the catalog once the dialog is open.
  const catalog = useModuleCatalog(open);

  function reset() {
    setName("");
    setDescription("");
    setMode("team");
    setVisibility("private");
    setPublicScoreboard(false);
    setStartAt("");
    setEndAt("");
    setDisabledModules(new Set());
    create.reset();
  }

  function toggleModule(id: string) {
    setDisabledModules((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    create.mutate(
      {
        name,
        description,
        participation_mode: mode,
        visibility,
        public_scoreboard: publicScoreboard,
        start_at: fromInput(startAt),
        end_at: fromInput(endAt),
        disabled_modules: [...disabledModules],
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
          <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
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

            <div className="space-y-1.5">
              <label className="flex items-center gap-2.5 text-sm font-medium">
                <input
                  type="checkbox"
                  className={CHECKBOX}
                  style={CHECKBOX_STYLE}
                  checked={publicScoreboard}
                  onChange={(e) => setPublicScoreboard(e.target.checked)}
                />
                Public scoreboard
              </label>
              <p className="pl-6 text-xs text-muted-foreground">
                Show a read-only spectator scoreboard at a public link — no account needed.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-2">
                <Label htmlFor="competition-start">Starts (optional)</Label>
                <Input
                  id="competition-start"
                  type="datetime-local"
                  value={startAt}
                  onChange={(e) => setStartAt(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="competition-end">Ends (optional)</Label>
                <Input
                  id="competition-end"
                  type="datetime-local"
                  value={endAt}
                  onChange={(e) => setEndAt(e.target.value)}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label>Modules</Label>
              <p className="text-xs text-muted-foreground">
                Optional modules are on by default. Turn off any this competition
                won&apos;t use — you can change these later in settings.
              </p>
              <ul className="rounded-md border border-border px-3">
                {catalog.isLoading && (
                  <li className="py-3 text-sm text-muted-foreground">Loading modules…</li>
                )}
                {catalog.data?.map((m) => {
                  const enabled = !disabledModules.has(m.id);
                  return (
                    <li
                      key={m.id}
                      className="flex items-center justify-between gap-3 border-b border-border py-3 last:border-0"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">{m.name}</span>
                          {enabled ? (
                            <Badge variant="success">Enabled</Badge>
                          ) : (
                            <Badge variant="outline">Disabled</Badge>
                          )}
                        </div>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {m.description}
                        </p>
                      </div>
                      <Button
                        type="button"
                        variant={enabled ? "outline" : "default"}
                        size="sm"
                        className="flex-shrink-0"
                        onClick={() => toggleModule(m.id)}
                      >
                        {enabled ? "Disable" : "Enable"}
                      </Button>
                    </li>
                  );
                })}
              </ul>
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
