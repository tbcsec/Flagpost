"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useUpdateCompetition } from "@/lib/hooks/use-competitions";
import type {
  Competition,
  ParticipationMode,
  Visibility,
} from "@/lib/types";
import { toast } from "@/stores/toast";

// datetime-local <-> stored ISO. The input value is treated as UTC so it
// round-trips without a timezone shift (timezone polish is a later tier).
const toInput = (iso: string | null) => (iso ? iso.slice(0, 16) : "");
const fromInput = (v: string) => (v ? new Date(`${v}Z`).toISOString() : null);

// Feature component. Edits go through the domain hook; RBAC is enforced
// server-side (a non-organiser's PATCH 403s, surfaced inline).
export function CompetitionSettingsForm({
  competition,
}: {
  competition: Competition;
}) {
  const update = useUpdateCompetition(competition.id);
  const [form, setForm] = useState({
    name: competition.name,
    description: competition.description,
    participation_mode: competition.participation_mode,
    visibility: competition.visibility,
    start_at: toInput(competition.start_at),
    end_at: toInput(competition.end_at),
    registration_opens_at: toInput(competition.registration_opens_at),
    registration_closes_at: toInput(competition.registration_closes_at),
  });

  function set<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    update.mutate(
      {
        name: form.name,
        description: form.description,
        participation_mode: form.participation_mode,
        visibility: form.visibility,
        start_at: fromInput(form.start_at),
        end_at: fromInput(form.end_at),
        registration_opens_at: fromInput(form.registration_opens_at),
        registration_closes_at: fromInput(form.registration_closes_at),
      },
      { onSuccess: () => toast("Changes saved", { variant: "success" }) },
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="name">Name</Label>
        <Input
          id="name"
          value={form.name}
          onChange={(e) => set("name", e.target.value)}
          required
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="description">Description</Label>
        <Input
          id="description"
          value={form.description}
          onChange={(e) => set("description", e.target.value)}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor="participation_mode">Participation mode</Label>
          <Select
            id="participation_mode"
            value={form.participation_mode}
            onChange={(e) =>
              set("participation_mode", e.target.value as ParticipationMode)
            }
          >
            <option value="team">Team</option>
            <option value="individual">Individual</option>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="visibility">Visibility</Label>
          <Select
            id="visibility"
            value={form.visibility}
            onChange={(e) => set("visibility", e.target.value as Visibility)}
          >
            <option value="private">Private</option>
            <option value="public">Public</option>
          </Select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <Label htmlFor="start_at">Starts</Label>
          <Input
            id="start_at"
            type="datetime-local"
            value={form.start_at}
            onChange={(e) => set("start_at", e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="end_at">Ends</Label>
          <Input
            id="end_at"
            type="datetime-local"
            value={form.end_at}
            onChange={(e) => set("end_at", e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="registration_opens_at">Registration opens</Label>
          <Input
            id="registration_opens_at"
            type="datetime-local"
            value={form.registration_opens_at}
            onChange={(e) => set("registration_opens_at", e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="registration_closes_at">Registration closes</Label>
          <Input
            id="registration_closes_at"
            type="datetime-local"
            value={form.registration_closes_at}
            onChange={(e) => set("registration_closes_at", e.target.value)}
          />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save changes"}
        </Button>
        {update.isSuccess && (
          <span className="text-sm text-muted-foreground">Saved.</span>
        )}
        {update.isError && (
          <span className="text-sm text-destructive">
            {(update.error as Error).message}
          </span>
        )}
      </div>
    </form>
  );
}
