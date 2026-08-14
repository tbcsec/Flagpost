"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { Select } from "@/components/ui/select";
import {
  useSetCompetitionStatus,
  useUpdateCompetition,
} from "@/lib/hooks/use-competitions";
import { useFreezeScoreboard } from "@/lib/hooks/use-scoreboard";
import { useAccess } from "@/lib/hooks/use-permissions";
import { richTextToPlain } from "@/lib/rich-text";
import type {
  Competition,
  CompetitionStatus,
  ParticipationMode,
  RichTextDoc,
  Visibility,
} from "@/lib/types";
import { toast } from "@/stores/toast";

// datetime-local <-> stored ISO. The input value is treated as UTC so it
// round-trips without a timezone shift (timezone polish is a later tier).
const toInput = (iso: string | null) => (iso ? iso.slice(0, 16) : "");
const fromInput = (v: string) => (v ? new Date(`${v}Z`).toISOString() : null);

const API_ORIGIN = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const STATUS_LABEL: Record<CompetitionStatus, string> = {
  not_started: "Not started",
  running: "Running",
  ended: "Ended",
};

// State pills for the Controls panel (design tokens, not raw colours).
const PILL = "shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ";
const PILL_RUNNING = "bg-success/15 text-success";
const PILL_NEUTRAL = "bg-muted text-muted-foreground";
const PILL_WARN = "bg-warning/15 text-warning";

export type SettingsSection = "general" | "schedule" | "challenges" | "rules";

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
  const setStatus = useSetCompetitionStatus(competition.id);
  const freeze = useFreezeScoreboard(competition.id);
  const access = useAccess();
  const confirm = useConfirm();
  // Each control's routes are gated on its own permission, so only offer the
  // button to a holder (the Settings tab opens on the broader edit/challenge
  // perms): status → manage_schedule, pause → edit_competition, freeze →
  // scoreboard_freeze.
  const canControlStatus = access.has("manage_schedule");
  const canPause = access.has("edit_competition");
  const canFreeze = access.has("scoreboard_freeze");
  const frozen = competition.scoreboard_frozen_at != null;

  async function onStart() {
    if (
      !(await confirm({
        title: competition.status === "ended" ? "Re-open the competition?" : "Start the competition?",
        description:
          "Competitors will immediately be able to view challenges, submit flags, and see the scoreboard.",
        confirmLabel: competition.status === "ended" ? "Re-open" : "Start",
        destructive: false,
      }))
    )
      return;
    setStatus.mutate("start", {
      onSuccess: () => toast("Competition started", { variant: "success" }),
      onError: (e) =>
        toast("Couldn't start", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  async function onStop() {
    if (
      !(await confirm({
        title: "Stop the competition?",
        description:
          "Challenge viewing and submissions close for competitors right away; the scoreboard stays visible as final standings. You can start it again later. Want a temporary stop instead? Pause the competition rather than stopping it.",
        confirmLabel: "Stop",
        destructive: true,
      }))
    )
      return;
    setStatus.mutate("stop", {
      onSuccess: () => toast("Competition stopped", { variant: "success" }),
      onError: (e) =>
        toast("Couldn't stop", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  function onTogglePause() {
    // Immediate action (not part of the form Save) — a run-day toggle, and
    // instantly reversible, so no confirmation.
    update.mutate(
      { paused: !competition.paused },
      {
        onSuccess: () =>
          toast(competition.paused ? "Competition resumed" : "Competition paused", {
            variant: "success",
          }),
        onError: (e) =>
          toast("Couldn't update", { description: (e as Error).message, variant: "destructive" }),
      },
    );
  }

  async function onToggleFreeze() {
    if (
      !frozen &&
      !(await confirm({
        title: "Freeze the scoreboard?",
        description:
          "Competitors keep solving and their points still count — the public board just stops showing movement until you unfreeze it. Staff can still view live standings.",
        confirmLabel: "Freeze",
        destructive: false,
      }))
    )
      return;
    freeze.mutate(!frozen, {
      onSuccess: () =>
        toast(frozen ? "Scoreboard unfrozen" : "Scoreboard frozen", { variant: "success" }),
      onError: (e) =>
        toast("Couldn't update the board", {
          description: (e as Error).message,
          variant: "destructive",
        }),
    });
  }

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
    mc_penalty_pct: competition.mc_penalty_pct ? String(competition.mc_penalty_pct) : "",
    challenge_ratings_enabled: competition.challenge_ratings_enabled,
    challenge_tags: competition.challenge_tags ?? [],
    difficulty_tiers: competition.difficulty_tiers ?? [],
    public_scoreboard: competition.public_scoreboard,
    ctftime_enabled: competition.ctftime_enabled,
    brackets: competition.brackets ?? [],
    max_team_size: competition.max_team_size ? String(competition.max_team_size) : "",
    rules_override: (competition.rules_override ?? {}) as RichTextDoc,
    rules_display_only: competition.rules_display_only,
  });

  function set<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    // A visually-empty editor doc means "no override" (fall back to the
    // site-wide rules) — send null, not an empty node tree.
    const rulesDoc = richTextToPlain(form.rules_override).trim()
      ? form.rules_override
      : null;
    const overrideChanged =
      JSON.stringify(rulesDoc) !==
      JSON.stringify(competition.rules_override ?? null);
    // Owner decision (#57): adding/changing an override resets every
    // participant's acceptance — warn the staff member before committing.
    if (
      overrideChanged &&
      rulesDoc &&
      !(await confirm({
        title: "Update the competition rules?",
        description:
          "Saving a new or changed rules override clears all existing acceptances — every participant will be prompted to accept the rules again before they can continue.",
        confirmLabel: "Save and re-prompt",
      }))
    ) {
      return;
    }
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
        // Blank clears the penalty (off); 1–100 sets it (#148).
        mc_penalty_pct: form.mc_penalty_pct ? Number(form.mc_penalty_pct) : null,
        challenge_ratings_enabled: form.challenge_ratings_enabled,
        challenge_tags: form.challenge_tags,
        difficulty_tiers: form.difficulty_tiers,
        public_scoreboard: form.public_scoreboard,
        ctftime_enabled: form.ctftime_enabled,
        brackets: form.brackets,
        max_team_size: form.max_team_size ? Number(form.max_team_size) : null,
        rules_override: rulesDoc,
        rules_display_only: form.rules_display_only,
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

          {form.participation_mode === "team" && (
            <div className="max-w-xs space-y-2">
              <Label htmlFor="max_team_size">Max team size</Label>
              <Input
                id="max_team_size"
                type="number"
                min={1}
                placeholder="Unlimited"
                value={form.max_team_size}
                onChange={(e) => set("max_team_size", e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Members allowed per team. Blank = unlimited.
              </p>
            </div>
          )}
        </>
      )}

      {section === "schedule" && (
        <div className="space-y-5">
          <p className="text-xs text-muted-foreground">
            Run-day controls plus the schedule. The three controls apply
            immediately; the schedule at the bottom saves with the form.
          </p>

          {/* Status — start / stop (#221) */}
          <div className="space-y-3 rounded-md border border-border bg-muted/30 p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <Label>Competition status</Label>
                <p className="mt-1 text-xs text-muted-foreground">
                  Competitors can play only while{" "}
                  <span className="font-medium">running</span> — otherwise
                  challenges show a closed message (the final scoreboard stays
                  visible after it ends). The schedule below moves this
                  automatically; Start / Stop override it now.
                </p>
              </div>
              <span
                className={
                  PILL + (competition.status === "running" ? PILL_RUNNING : PILL_NEUTRAL)
                }
              >
                {STATUS_LABEL[competition.status]}
              </span>
            </div>
            {canControlStatus && (
              <div className="flex flex-wrap gap-2">
                {competition.status !== "running" ? (
                  <Button type="button" size="sm" onClick={onStart} disabled={setStatus.isPending}>
                    {competition.status === "ended" ? "Re-open competition" : "Start competition"}
                  </Button>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={onStop}
                    disabled={setStatus.isPending}
                  >
                    Stop competition
                  </Button>
                )}
              </div>
            )}
          </div>

          {/* Pause — halt submissions (moved here from General) */}
          <div className="space-y-3 rounded-md border border-border bg-muted/30 p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <Label>Gameplay pause</Label>
                <p className="mt-1 text-xs text-muted-foreground">
                  Temporarily halt gameplay — competitors can&apos;t submit flags
                  (staff still can, to test). Instantly reversible, and separate
                  from stopping (which ends the competition) or freezing the board.
                </p>
              </div>
              {competition.paused && <span className={PILL + PILL_WARN}>Paused</span>}
            </div>
            {canPause && (
              <Button
                type="button"
                size="sm"
                variant={competition.paused ? "default" : "secondary"}
                onClick={onTogglePause}
                disabled={update.isPending}
              >
                {competition.paused ? "Resume competition" : "Pause competition"}
              </Button>
            )}
          </div>

          {/* Freeze — scoreboard */}
          <div className="space-y-3 rounded-md border border-border bg-muted/30 p-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <Label>Scoreboard freeze</Label>
                <p className="mt-1 text-xs text-muted-foreground">
                  Freeze the public board at its current standings — competitors
                  keep solving and their points still count, but the board stops
                  showing movement until you unfreeze it. Staff still see live
                  standings.
                </p>
              </div>
              {frozen && <span className={PILL + PILL_NEUTRAL}>Frozen</span>}
            </div>
            {canFreeze && (
              <Button
                type="button"
                size="sm"
                variant={frozen ? "default" : "secondary"}
                onClick={onToggleFreeze}
                disabled={freeze.isPending}
              >
                {freeze.isPending
                  ? "Saving…"
                  : frozen
                    ? "Unfreeze scoreboard"
                    : "Freeze scoreboard"}
              </Button>
            )}
          </div>

          {/* Schedule (saved with the form) */}
          <div className="space-y-2 border-t border-border pt-4">
            <Label>Schedule</Label>
            <p className="text-xs text-muted-foreground">
              When play auto-starts / ends and when registration is open. Saved
              with the form; a manual Start / Stop above overrides these.
            </p>
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
          </div>
        </div>
      )}

      {section === "rules" && (
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Rules / code of conduct override</Label>
            <p className="text-xs text-muted-foreground">
              Supersedes the site-wide rules for this competition. Leave empty
              to use the site-wide document (Admin → Site settings). Unless
              display-only is on, users must accept the effective rules before
              they can join{competition.participation_mode === "team" ? " or create/join a team" : ""}.
            </p>
            <RichTextEditor
              value={form.rules_override}
              onChange={(doc) => set("rules_override", doc)}
            />
          </div>
          <label className="flex items-start gap-2.5 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 rounded border-border"
              style={{ accentColor: "hsl(var(--primary))" }}
              checked={form.rules_display_only}
              onChange={(e) => set("rules_display_only", e.target.checked)}
            />
            <span>
              Display only
              <span className="ml-1 text-xs text-muted-foreground">
                — show the rules at join without requiring an explicit
                &ldquo;I accept&rdquo; (nothing blocks the join).
              </span>
            </span>
          </label>
          <p className="text-xs text-muted-foreground">
            Saving a new or changed override prompts every participant to
            accept the rules again. Staff with competition-edit access never
            see the prompt.
          </p>
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
          <div className="mt-3 space-y-2">
            <Label htmlFor="mc_penalty_pct">Wrong-guess penalty (%)</Label>
            <Input
              id="mc_penalty_pct"
              type="number"
              min={1}
              max={100}
              placeholder="Off"
              value={form.mc_penalty_pct}
              onChange={(e) => set("mc_penalty_pct", e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Each wrong guess on a multiple-choice question lowers its value for
              that team/competitor by this percent, so a later correct answer
              awards less (floored at 0). Blank = off. Pairs with the guess limit.
            </p>
          </div>
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
