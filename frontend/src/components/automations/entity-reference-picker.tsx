"use client";

// Name-search dropdown for an automation id field (#212, ARCHITECTURE §9 — "ids
// are internal, never shown to users"). Given an entity_type the builder loads
// that entity's list through its domain hook and stores the id while displaying
// the human name — no raw id box anywhere.
//
// Competition-scoped entities (challenge/survey/hint/team/user) need a
// competition first: a competition-scoped *rule* supplies it, a global rule has
// none so the picker asks for one inline ("challenges for that selected
// competition"). A hint is one level deeper still — competition → challenge →
// hint. All list hooks are called unconditionally (rules of hooks) and gated to
// idle by passing an empty scope, so only the relevant list actually fetches.

import * as React from "react";

import {
  EntityCombobox,
  type ComboOption,
} from "@/components/ui/entity-combobox";
import { useChallenges } from "@/lib/hooks/use-challenges";
import { useCompetitions } from "@/lib/hooks/use-competitions";
import { useSurveys } from "@/lib/hooks/use-feedback";
import { useHints } from "@/lib/hooks/use-hints";
import { useParticipants } from "@/lib/hooks/use-participants";
import { useTeams } from "@/lib/hooks/use-teams";
import type { EntityRefType } from "@/lib/types";

const COMPETITION_SCOPED: ReadonlySet<EntityRefType> = new Set<EntityRefType>([
  "challenge",
  "survey",
  "hint",
  "team",
  "user",
]);

const PLACEHOLDER: Record<EntityRefType, string> = {
  competition: "Pick a competition",
  challenge: "Pick a challenge",
  survey: "Pick a survey",
  hint: "Pick a hint",
  team: "Pick a team",
  user: "Pick a participant",
  role: "Pick a role",
};

/** Hints have no title — label them by position with a short body preview. */
function hintLabel(body: string | null, cost: number, index: number): string {
  const preview = (body ?? "").replace(/\s+/g, " ").trim().slice(0, 40);
  const suffix = cost > 0 ? ` · ${cost} pts` : "";
  return preview ? `${index + 1}. ${preview}${suffix}` : `Hint ${index + 1}${suffix}`;
}

export function EntityReferencePicker({
  entityType,
  competitionId,
  value,
  onChange,
  id,
  disabled,
}: {
  entityType: EntityRefType;
  /** The rule's competition; undefined for a global rule (asks for scope). */
  competitionId?: string;
  value: string;
  onChange: (value: string) => void;
  id?: string;
  disabled?: boolean;
}) {
  const scoped = COMPETITION_SCOPED.has(entityType);
  // Global-rule scope choices — local UI state, never stored in the rule config.
  const [scopeComp, setScopeComp] = React.useState("");
  const [scopeChallenge, setScopeChallenge] = React.useState("");
  const effectiveComp = competitionId ?? scopeComp;

  // Each hook fetches only when this entity_type needs it (empty scope = idle).
  const challengeScope =
    entityType === "challenge" || entityType === "hint" ? effectiveComp : "";
  const competitions = useCompetitions();
  const challenges = useChallenges(challengeScope);
  const surveys = useSurveys(entityType === "survey" ? effectiveComp : "");
  const teams = useTeams(entityType === "team" ? effectiveComp : "");
  const participants = useParticipants(
    entityType === "user" ? effectiveComp : "",
    entityType === "user" && Boolean(effectiveComp),
  );
  const hints = useHints(
    entityType === "hint" ? effectiveComp : "",
    scopeChallenge,
  );

  const competitionOptions: ComboOption[] = (competitions.data ?? []).map(
    (c) => ({ value: c.id, label: c.name }),
  );
  const challengeOptions: ComboOption[] = (challenges.data ?? []).map((c) => ({
    value: c.id,
    label: c.title,
  }));

  let options: ComboOption[] = [];
  switch (entityType) {
    case "competition":
      options = competitionOptions;
      break;
    case "challenge":
      options = challengeOptions;
      break;
    case "survey":
      options = (surveys.data ?? []).map((s) => ({ value: s.id, label: s.title }));
      break;
    case "team":
      options = (teams.data ?? []).map((t) => ({ value: t.id, label: t.name }));
      break;
    case "user":
      options = (participants.data ?? []).map((p) => ({
        value: p.user_id,
        label: p.display_name,
      }));
      break;
    case "hint":
      options = (hints.data ?? []).map((h, i) => ({
        value: h.id,
        label: hintLabel(h.body, h.cost, i),
      }));
      break;
    // No list hook feeds "role" (notify.role_name stays a plain name field) or
    // any other unmapped type, so this yields no options. CONTRACT: adding a new
    // entity_type to a catalog field REQUIRES wiring its list hook + a case
    // above — otherwise the builder silently renders a dead, empty dropdown here.
    default:
      options = [];
  }

  // Non-scoped reference (a competition itself): a single dropdown.
  if (!scoped) {
    return (
      <EntityCombobox
        id={id}
        options={options}
        value={value}
        onChange={onChange}
        placeholder={PLACEHOLDER[entityType]}
        emptyText="No matches"
        disabled={disabled}
        className="h-9"
      />
    );
  }

  const entityDisabled =
    disabled || !effectiveComp || (entityType === "hint" && !scopeChallenge);

  return (
    <div className="space-y-2">
      {/* A global rule has no competition — pick one to scope the list. */}
      {!competitionId && (
        <EntityCombobox
          options={competitionOptions}
          value={scopeComp}
          onChange={(v) => {
            setScopeComp(v);
            setScopeChallenge("");
            onChange(""); // the previous pick belonged to another competition
          }}
          placeholder="Pick a competition"
          emptyText="No competitions"
          className="h-9"
        />
      )}
      {/* A hint lives under a challenge — pick that first. */}
      {entityType === "hint" && (
        <EntityCombobox
          options={challengeOptions}
          value={scopeChallenge}
          onChange={(v) => {
            setScopeChallenge(v);
            onChange("");
          }}
          placeholder="Pick a challenge"
          emptyText={effectiveComp ? "No challenges" : "Pick a competition first"}
          disabled={!effectiveComp}
          className="h-9"
        />
      )}
      <EntityCombobox
        id={id}
        options={options}
        value={value}
        onChange={onChange}
        placeholder={PLACEHOLDER[entityType]}
        emptyText={effectiveComp ? "No matches" : "Pick a competition first"}
        disabled={entityDisabled}
        className="h-9"
      />
    </div>
  );
}
