// Pure serialization between the visual builder's state and the automation
// rule JSON model (ARCHITECTURE.md §5.1, §5.5). Kept out of the component so
// the round-trip (build → API shape → parse back) is unit-testable without a
// DOM. Every config value is a *string* in builder state (that's what inputs
// produce); coercion to the typed API shape — numbers, string lists, header
// maps — happens only at the boundary here.

import type {
  ActionCatalogEntry,
  AutomationCatalog,
  AutomationCondition,
  AutomationRule,
  AutomationRuleInput,
} from "@/lib/types";

export interface BuilderAction {
  type: string;
  config: Record<string, string>;
}

export interface BuilderState {
  name: string;
  trigger_type: string;
  is_enabled: boolean;
  conditions: AutomationCondition[];
  actions: BuilderAction[];
}

/** A fresh rule seeded from the catalog: first trigger, no conditions, one
 *  action of the first type offered (org: notify targeting the event user;
 *  personal: notify-self — see {@link actionsFor}). */
export function blankRule(
  catalog: AutomationCatalog,
  personal: boolean,
): BuilderState {
  const actions = actionsFor(catalog, personal);
  const firstAction = actions[0];
  return {
    name: "",
    trigger_type: catalog.triggers[0]?.event ?? "",
    is_enabled: true,
    conditions: [],
    actions: firstAction ? [blankAction(firstAction, personal)] : [],
  };
}

/** The action types a rule of this kind may use: personal rules are
 *  notify-self only (§5.1), org rules get the full set. */
export function actionsFor(
  catalog: AutomationCatalog,
  personal: boolean,
): ActionCatalogEntry[] {
  return personal
    ? catalog.actions.filter((a) => a.personal_allowed)
    : catalog.actions;
}

/** The `notify` target options for this context: personal → self only; org →
 *  everything but self (an org rule has no owner to notify). */
export function targetOptionsFor(
  options: string[],
  personal: boolean,
): string[] {
  return personal ? ["self"] : options.filter((o) => o !== "self");
}

export function blankAction(
  entry: ActionCatalogEntry,
  personal: boolean,
): BuilderAction {
  const config: Record<string, string> = {};
  for (const field of entry.fields) {
    if (field.kind === "select" && field.options?.length) {
      const options =
        field.key === "target"
          ? targetOptionsFor(field.options, personal)
          : field.options;
      config[field.key] = options[0] ?? "";
    } else {
      config[field.key] = "";
    }
  }
  return { type: entry.type, config };
}

function parseKeyValues(raw: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of raw.split("\n")) {
    const idx = line.indexOf(":");
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    if (key) out[key] = value;
  }
  return out;
}

function coerceField(
  kind: string,
  raw: string,
): string | number | string[] | Record<string, string> {
  switch (kind) {
    case "number": {
      const n = Number(raw);
      return Number.isFinite(n) ? n : raw; // let the backend 422 on garbage
    }
    case "string_list":
      return raw
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean);
    case "keyvalue":
      return parseKeyValues(raw);
    default:
      return raw;
  }
}

/** Builder state → the API's AutomationRuleInput. Empty optional fields are
 *  dropped; conditions with no field are dropped; a unary operator
 *  (exists/not_exists) carries no value. */
export function toRuleInput(
  state: BuilderState,
  catalog: AutomationCatalog,
): AutomationRuleInput {
  const unary = new Set(
    catalog.operators.filter((o) => o.unary).map((o) => o.value),
  );
  const actionByType = new Map(catalog.actions.map((a) => [a.type, a]));

  return {
    name: state.name.trim(),
    trigger_type: state.trigger_type,
    is_enabled: state.is_enabled,
    conditions: state.conditions
      .filter((c) => c.field.trim())
      .map((c) =>
        unary.has(c.operator)
          ? { field: c.field.trim(), operator: c.operator }
          : { field: c.field.trim(), operator: c.operator, value: c.value },
      ),
    actions: state.actions.map((action) => {
      const entry = actionByType.get(action.type);
      const out: Record<string, unknown> = { type: action.type };
      for (const field of entry?.fields ?? []) {
        const raw = action.config[field.key] ?? "";
        if (raw === "" && !field.required) continue;
        out[field.key] = coerceField(field.kind, raw);
      }
      return out as AutomationRuleInput["actions"][number];
    }),
  };
}

function stringifyField(kind: string, value: unknown): string {
  if (value === undefined || value === null) return "";
  if (kind === "string_list" && Array.isArray(value)) return value.join("\n");
  if (kind === "keyvalue" && value && typeof value === "object") {
    return Object.entries(value as Record<string, string>)
      .map(([k, v]) => `${k}: ${v}`)
      .join("\n");
  }
  return String(value);
}

/** An existing rule → builder state (the inverse of {@link toRuleInput}), so a
 *  rule opens in the editor exactly as it was saved. */
export function fromRule(
  rule: AutomationRule,
  catalog: AutomationCatalog,
): BuilderState {
  const actionByType = new Map(catalog.actions.map((a) => [a.type, a]));
  return {
    name: rule.name,
    trigger_type: rule.trigger_type,
    is_enabled: rule.is_enabled,
    conditions: rule.conditions.map((c) => ({
      field: c.field,
      operator: c.operator,
      value: c.value === undefined || c.value === null ? "" : String(c.value),
    })),
    actions: rule.actions.map((action) => {
      const entry = actionByType.get(action.type as string);
      const config: Record<string, string> = {};
      for (const field of entry?.fields ?? []) {
        config[field.key] = stringifyField(field.kind, action[field.key]);
      }
      return { type: action.type as string, config };
    }),
  };
}
