import { describe, expect, it } from "vitest";

import {
  actionsFor,
  blankAction,
  blankRule,
  fromRule,
  targetOptionsFor,
  toRuleInput,
} from "@/lib/automation-builder";
import type { AutomationCatalog, AutomationRule } from "@/lib/types";

const catalog: AutomationCatalog = {
  triggers: [
    {
      event: "challenge.solved",
      label: "Challenge solved",
      fields: ["points", "is_first_blood", "user_id"],
    },
  ],
  operators: [
    { value: "equals", label: "equals", unary: false },
    { value: "gt", label: "greater than", unary: false },
    { value: "exists", label: "is present", unary: true },
  ],
  actions: [
    {
      type: "notify",
      label: "Notify",
      personal_allowed: true,
      fields: [
        { key: "target", label: "Notify", kind: "select", required: true, options: ["event_user", "event_team", "role", "self"], placeholder: null, templateable: false },
        { key: "title", label: "Title", kind: "text", required: true, options: null, placeholder: null, templateable: true },
        { key: "body", label: "Body", kind: "textarea", required: false, options: null, placeholder: null, templateable: true },
      ],
    },
    {
      type: "update_score",
      label: "Update score",
      personal_allowed: false,
      fields: [
        { key: "points", label: "Points", kind: "number", required: true, options: null, placeholder: null, templateable: false },
        { key: "reason", label: "Reason", kind: "text", required: true, options: null, placeholder: null, templateable: true },
      ],
    },
    {
      type: "webhook",
      label: "Webhook",
      personal_allowed: false,
      fields: [
        { key: "url", label: "URL", kind: "text", required: true, options: null, placeholder: null, templateable: false },
        { key: "headers", label: "Headers", kind: "keyvalue", required: false, options: null, placeholder: null, templateable: false },
        { key: "send_to", label: "Recipients", kind: "string_list", required: false, options: null, placeholder: null, templateable: false },
      ],
    },
  ],
};

describe("action availability by rule kind (§5.1)", () => {
  it("personal rules get only notify-self", () => {
    expect(actionsFor(catalog, true).map((a) => a.type)).toEqual(["notify"]);
    expect(targetOptionsFor(["event_user", "role", "self"], true)).toEqual(["self"]);
  });
  it("org rules get everything but a self target", () => {
    expect(actionsFor(catalog, false).map((a) => a.type)).toEqual([
      "notify",
      "update_score",
      "webhook",
    ]);
    expect(targetOptionsFor(["event_user", "role", "self"], false)).toEqual([
      "event_user",
      "role",
    ]);
  });
});

describe("blank seeds", () => {
  it("blankRule picks the first trigger + one default action", () => {
    const state = blankRule(catalog, false);
    expect(state.trigger_type).toBe("challenge.solved");
    expect(state.is_enabled).toBe(true);
    expect(state.conditions).toEqual([]);
    expect(state.actions).toHaveLength(1);
    // org default target is the first non-self option.
    expect(state.actions[0].config.target).toBe("event_user");
  });
  it("personal blankAction defaults the target to self", () => {
    const action = blankAction(catalog.actions[0], true);
    expect(action.config.target).toBe("self");
  });
});

describe("toRuleInput coercion", () => {
  it("coerces number/list/keyvalue and drops empties + unary values", () => {
    const input = toRuleInput(
      {
        name: "  Bonus  ",
        trigger_type: "challenge.solved",
        is_enabled: true,
        conditions: [
          { field: "points", operator: "gt", value: "100" },
          { field: "user_id", operator: "exists", value: "ignored" },
          { field: "  ", operator: "equals", value: "x" }, // dropped: no field
        ],
        actions: [
          { type: "update_score", config: { points: "50", reason: "First blood" } },
          {
            type: "webhook",
            config: {
              url: "https://x.example",
              headers: "X-Token: abc\nmalformed line\nAccept: */*",
              send_to: "a@x.com, b@x.com\nc@x.com",
            },
          },
        ],
      },
      catalog,
    );

    expect(input.name).toBe("Bonus"); // trimmed
    expect(input.conditions).toEqual([
      { field: "points", operator: "gt", value: "100" },
      { field: "user_id", operator: "exists" }, // unary → no value
    ]);
    const [score, webhook] = input.actions;
    expect(score).toEqual({ type: "update_score", points: 50, reason: "First blood" });
    expect(webhook).toEqual({
      type: "webhook",
      url: "https://x.example",
      headers: { "X-Token": "abc", Accept: "*/*" }, // malformed line skipped
      send_to: ["a@x.com", "b@x.com", "c@x.com"],
    });
  });

  it("omits an empty optional field", () => {
    const input = toRuleInput(
      {
        name: "n",
        trigger_type: "challenge.solved",
        is_enabled: true,
        conditions: [],
        actions: [{ type: "notify", config: { target: "event_user", title: "hi", body: "" } }],
      },
      catalog,
    );
    expect(input.actions[0]).toEqual({ type: "notify", target: "event_user", title: "hi" });
  });
});

describe("fromRule is the inverse", () => {
  it("round-trips a saved rule back into editable string config", () => {
    const rule: AutomationRule = {
      id: "r1",
      name: "Bonus",
      trigger_type: "challenge.solved",
      conditions: [{ field: "is_first_blood", operator: "equals", value: true }],
      actions: [
        { type: "update_score", points: -25, reason: "penalty" },
        { type: "webhook", url: "https://x", headers: { A: "1", B: "2" }, send_to: ["a@x", "b@x"] },
      ],
      is_enabled: false,
      competition_id: "c1",
      owner_user_id: null,
      trigger_count: 3,
      last_triggered_at: null,
      created_at: "2026-07-22T00:00:00Z",
    };
    const state = fromRule(rule, catalog);
    expect(state.conditions[0]).toEqual({
      field: "is_first_blood",
      operator: "equals",
      value: "true",
    });
    expect(state.actions[0].config).toEqual({ points: "-25", reason: "penalty" });
    expect(state.actions[1].config.headers).toBe("A: 1\nB: 2");
    expect(state.actions[1].config.send_to).toBe("a@x\nb@x");

    // and back out again yields the typed shape.
    const back = toRuleInput(state, catalog);
    expect(back.actions[0]).toEqual({ type: "update_score", points: -25, reason: "penalty" });
    expect(back.actions[1]).toMatchObject({ headers: { A: "1", B: "2" }, send_to: ["a@x", "b@x"] });
  });
});
