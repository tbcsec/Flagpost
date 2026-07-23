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

const API_ORIGIN = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type SettingsSection = "general" | "schedule" | "challenges";

// Feature component. Edits go through the domain hook; RBAC is enforced
// server-side (a non-organiser's PATCH 403s, surfaced inline). One form + one
// Save across all sections — the page shows one section at a time via tabs, but
// the state lives here so switching tabs never loses an unsaved edit.
export function CompetitionSettingsForm({
  competition,
  section,
}: {
  competition: Competition;
  section: SettingsSection;
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
    mc_guess_limit: competition.mc_guess_limit ? String(competition.mc_guess_limit) : "",
    challenge_ratings_enabled: competition.challenge_ratings_enabled,
    challenge_tags: competition.challenge_tags ?? [],
    difficulty_tiers: competition.difficulty_tiers ?? [],
    public_scoreboard: competition.public_scoreboard,
    ctftime_enabled: competition.ctftime_enabled,
    brackets: competition.brackets ?? [],
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
        // Blank clears the cap (null); a positive number sets it.
        mc_guess_limit: form.mc_guess_limit ? Number(form.mc_guess_limit) : null,
        challenge_ratings_enabled: form.challenge_ratings_enabled,
        challenge_tags: form.challenge_tags,
        difficulty_tiers: form.difficulty_tiers,
        public_scoreboard: form.public_scoreboard,
        ctftime_enabled: form.ctftime_enabled,
        brackets: form.brackets,
      },
      { onSuccess: () => toast("Changes saved", { variant: "success" }) },
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {section === "general" && (
        <>
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

          <div className="space-y-3 border-t border-border pt-4">
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Public standings
            </h3>
            <label className="flex items-start gap-2.5 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 rounded border-border"
                style={{ accentColor: "hsl(var(--primary))" }}
                checked={form.public_scoreboard}
                onChange={(e) => set("public_scoreboard", e.target.checked)}
              />
              <span>
                Public scoreboard
                <span className="ml-1 text-xs text-muted-foreground">
                  (lists this competition on{" "}
                  <a className="underline" href="/public" target="_blank" rel="noreferrer">
                    /public
                  </a>{" "}
                  and lets anyone view the board without an account)
                </span>
              </span>
            </label>
            <label className="flex items-start gap-2.5 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 rounded border-border"
                style={{ accentColor: "hsl(var(--primary))" }}
                checked={form.ctftime_enabled}
                onChange={(e) => set("ctftime_enabled", e.target.checked)}
              />
              <span>
                CTFtime scoreboard feed
                <span className="ml-1 text-xs text-muted-foreground">
                  (exposes a CTFtime-format feed so the event can be rated on ctftime.org)
                </span>
              </span>
            </label>
            {form.ctftime_enabled && (
              <p className="text-xs text-muted-foreground">
                Feed URL:{" "}
                <a
                  className="font-mono text-primary underline"
                  href={`${API_ORIGIN}/api/public/competitions/${competition.id}/ctftime`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {API_ORIGIN}/api/public/competitions/{competition.id}/ctftime
                </a>
              </p>
            )}
          </div>

          <div className="border-t border-border pt-4">
            <VocabEditor
              label="Brackets / divisions"
              hint="Parallel rankings competitors self-select (e.g. Students, Open). Leave empty for a single ranking."
              values={form.brackets}
              onChange={(v) => set("brackets", v)}
              placeholder="Add a bracket…"
            />
          </div>
        </>
      )}

      {section === "schedule" && (
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
      )}

      {section === "challenges" && (
        <div className="space-y-6">
        <VocabEditor
          label="Difficulty tiers"
          hint="Ordered labels (e.g. Easy, Medium, Hard) authors pick from on a challenge."
          values={form.difficulty_tiers}
          onChange={(v) => set("difficulty_tiers", v)}
          placeholder="Add a tier…"
        />
        <VocabEditor
          label="Tags"
          hint="The tag vocabulary authors may apply to challenges."
          values={form.challenge_tags}
          onChange={(v) => set("challenge_tags", v)}
          placeholder="Add a tag…"
        />
        <div className="max-w-xs space-y-2">
          <Label htmlFor="mc_guess_limit">Multiple-choice guess limit</Label>
          <Input
            id="mc_guess_limit"
            type="number"
            min={1}
            max={1000}
            placeholder="Unlimited"
            value={form.mc_guess_limit}
            onChange={(e) => set("mc_guess_limit", e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Guesses each competitor (or team) gets per multiple-choice question, to
            curb brute-forcing. Blank = unlimited. Applies competition-wide.
          </p>
          <label className="mt-2 flex items-center gap-2.5 text-sm">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-border"
              style={{ accentColor: "hsl(var(--primary))" }}
              checked={form.challenge_ratings_enabled}
              onChange={(e) => set("challenge_ratings_enabled", e.target.checked)}
            />
            <span>
              Ask competitors to rate a challenge (1–5) after solving it
              <span className="ml-1 text-xs text-muted-foreground">
                (needs the Feedback module; results on the Feedback page)
              </span>
            </span>
          </label>
        </div>
        </div>
      )}

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

// A managed list of short labels (tags / difficulty tiers): add via the input,
// remove via the chip's ×. Order is preserved (difficulty tiers are ordered).
function VocabEditor({
  label,
  hint,
  values,
  onChange,
  placeholder,
}: {
  label: string;
  hint: string;
  values: string[];
  onChange: (values: string[]) => void;
  placeholder: string;
}) {
  const [draft, setDraft] = useState("");

  function add() {
    const v = draft.trim();
    if (v && !values.includes(v)) onChange([...values, v]);
    setDraft("");
  }

  return (
    <div className="max-w-md space-y-2">
      <Label>{label}</Label>
      <p className="text-xs text-muted-foreground">{hint}</p>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((v) => (
            <span
              key={v}
              className="inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-0.5 text-xs"
            >
              {v}
              <button
                type="button"
                onClick={() => onChange(values.filter((x) => x !== v))}
                className="text-muted-foreground hover:text-destructive"
                aria-label={`Remove ${v}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={placeholder}
          maxLength={50}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button type="button" variant="outline" onClick={add} disabled={!draft.trim()}>
          Add
        </Button>
      </div>
    </div>
  );
}
