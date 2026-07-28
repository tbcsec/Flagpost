import type { CompetitionRules, RichTextDoc } from "@/lib/types";

// Pure gating logic for the rules/CoC prompt (#57), kept out of the modal
// component so it's unit-testable without a DOM: given the server's rules
// state, what should a join flow do before firing the join?
//
//  - "accept"  → mandatory rules the user hasn't accepted: show the modal
//                with the checkbox-gated Accept button; join only after the
//                acceptance resolves.
//  - "display" → informational-only rules: show them with a plain Continue
//                (nothing recorded, never blocking).
//  - null      → nothing to show (no rules, already accepted, or staff).
export type RulesPromptMode = "accept" | "display" | null;

export function rulesPromptMode(
  state: Pick<
    CompetitionRules,
    "rules" | "display_only" | "accepted" | "exempt"
  >,
): RulesPromptMode {
  if (!state.rules || state.exempt) return null;
  if (state.display_only) return "display";
  return state.accepted ? null : "accept";
}

/** The rules-gate rejection a join endpoint raises (HTTP 403) when mandatory
 *  rules haven't been accepted. The payload carries the document itself so the
 *  invite-code flow can render the prompt straight from the error. */
export interface RulesGateRejection {
  competitionId: string;
  rules: RichTextDoc;
}

/** Parse an unknown error into a rules-gate rejection, or null when the error
 *  is anything else. Accepts the `ApiError.detail` payload shape. */
export function rulesGateRejection(err: unknown): RulesGateRejection | null {
  const detail = (err as { detail?: unknown } | null)?.detail;
  if (!detail || typeof detail !== "object") return null;
  const d = detail as {
    code?: unknown;
    competition_id?: unknown;
    rules?: unknown;
  };
  if (d.code !== "rules_not_accepted") return null;
  if (typeof d.competition_id !== "string" || !d.rules) return null;
  return {
    competitionId: d.competition_id,
    rules: d.rules as RichTextDoc,
  };
}
