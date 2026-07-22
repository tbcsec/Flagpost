"use client";

// Visual rule builder (ARCHITECTURE.md §5.5): a node-flow Trigger → Conditions
// → Actions editor, generated from the /catalog so a new action type is a
// backend-only change. Serialization lives in lib/automation-builder (pure,
// tested); this component is just the flow UI over that state.

import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  actionsFor,
  blankAction,
  blankRule,
  fromRule,
  targetOptionsFor,
  toRuleInput,
  type BuilderAction,
  type BuilderState,
} from "@/lib/automation-builder";
import type {
  AutomationCatalog,
  AutomationRule,
  AutomationRuleInput,
  CatalogField,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const TEXTAREA_CLASS =
  "flex min-h-16 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

export function RuleBuilder({
  open,
  onOpenChange,
  catalog,
  personal,
  initial,
  onSubmit,
  saving,
  error,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  catalog: AutomationCatalog;
  personal: boolean;
  initial?: AutomationRule;
  onSubmit: (input: AutomationRuleInput) => void;
  saving?: boolean;
  error?: string | null;
}) {
  const [state, setState] = React.useState<BuilderState>(() =>
    initial ? fromRule(initial, catalog) : blankRule(catalog, personal),
  );

  // Reseed whenever the dialog opens (or the rule being edited changes), so a
  // reused dialog never shows the previous rule's state.
  React.useEffect(() => {
    if (open) {
      setState(initial ? fromRule(initial, catalog) : blankRule(catalog, personal));
    }
  }, [open, initial, catalog, personal]);

  const availableActions = actionsFor(catalog, personal);
  const trigger = catalog.triggers.find((t) => t.event === state.trigger_type);
  const triggerFields = trigger?.fields ?? [];
  const actionByType = new Map(catalog.actions.map((a) => [a.type, a]));

  const isValid =
    state.name.trim() !== "" &&
    state.actions.length > 0 &&
    state.actions.every((a) => {
      const entry = actionByType.get(a.type);
      return (entry?.fields ?? []).every(
        (f) => !f.required || (a.config[f.key] ?? "").trim() !== "",
      );
    });

  function patch(next: Partial<BuilderState>) {
    setState((s) => ({ ...s, ...next }));
  }

  function updateCondition(idx: number, next: Partial<BuilderState["conditions"][number]>) {
    setState((s) => ({
      ...s,
      conditions: s.conditions.map((c, i) => (i === idx ? { ...c, ...next } : c)),
    }));
  }

  function updateAction(idx: number, next: BuilderAction) {
    setState((s) => ({
      ...s,
      actions: s.actions.map((a, i) => (i === idx ? next : a)),
    }));
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{initial ? "Edit rule" : personal ? "New personal rule" : "New rule"}</DialogTitle>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label htmlFor="rule-name">Name</Label>
          <Input
            id="rule-name"
            value={state.name}
            onChange={(e) => patch({ name: e.target.value })}
            placeholder="e.g. First-blood bonus"
          />
        </div>

        <datalist id="trigger-fields">
          {triggerFields.map((f) => (
            <option key={f} value={f} />
          ))}
        </datalist>

        <ol>
          {/* 1 — Trigger */}
          <Step index={1} label="When this happens">
            <Select
              value={state.trigger_type}
              onChange={(e) => patch({ trigger_type: e.target.value, conditions: [] })}
            >
              {catalog.triggers.map((t) => (
                <option key={t.event} value={t.event}>
                  {t.label}
                </option>
              ))}
            </Select>
          </Step>

          {/* 2 — Conditions */}
          <Step index={2} label="And these are all true (optional)">
            {state.conditions.length === 0 ? (
              <p className="text-[13px] text-muted-foreground">
                No conditions — runs on every <span className="text-foreground">{trigger?.label}</span>.
              </p>
            ) : (
              <div className="space-y-2">
                {state.conditions.map((c, i) => {
                  const op = catalog.operators.find((o) => o.value === c.operator);
                  return (
                    <div key={i} className="flex flex-wrap items-center gap-2">
                      <Input
                        list="trigger-fields"
                        value={c.field}
                        onChange={(e) => updateCondition(i, { field: e.target.value })}
                        placeholder="field"
                        className="h-9 w-36"
                      />
                      <Select
                        value={c.operator}
                        onChange={(e) => updateCondition(i, { operator: e.target.value })}
                        className="h-9 w-40"
                      >
                        {catalog.operators.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </Select>
                      {!op?.unary && (
                        <Input
                          value={c.value == null ? "" : String(c.value)}
                          onChange={(e) => updateCondition(i, { value: e.target.value })}
                          placeholder="value"
                          className="h-9 w-36"
                        />
                      )}
                      <IconButton
                        label="Remove condition"
                        onClick={() =>
                          patch({ conditions: state.conditions.filter((_, j) => j !== i) })
                        }
                      />
                    </div>
                  );
                })}
              </div>
            )}
            <button
              type="button"
              onClick={() =>
                patch({
                  conditions: [
                    ...state.conditions,
                    { field: "", operator: catalog.operators[0]?.value ?? "equals", value: "" },
                  ],
                })
              }
              className="mt-2 text-xs font-medium text-primary hover:underline"
            >
              + Add condition
            </button>
          </Step>

          {/* 3 — Actions */}
          <Step index={3} label="Do this" last>
            <div className="space-y-3">
              {state.actions.map((action, i) => {
                const entry = actionByType.get(action.type);
                return (
                  <div key={i} className="rounded-md border border-border bg-background/40 p-3">
                    <div className="flex items-center gap-2">
                      <Select
                        value={action.type}
                        onChange={(e) => {
                          const next = availableActions.find((a) => a.type === e.target.value);
                          if (next) updateAction(i, blankAction(next, personal));
                        }}
                        className="h-9 flex-1"
                      >
                        {availableActions.map((a) => (
                          <option key={a.type} value={a.type}>
                            {a.label}
                          </option>
                        ))}
                      </Select>
                      {state.actions.length > 1 && (
                        <IconButton
                          label="Remove action"
                          onClick={() =>
                            patch({ actions: state.actions.filter((_, j) => j !== i) })
                          }
                        />
                      )}
                    </div>
                    <div className="mt-3 space-y-3">
                      {(entry?.fields ?? []).map((field) => (
                        <FieldInput
                          key={field.key}
                          field={field}
                          personal={personal}
                          triggerFields={triggerFields}
                          value={action.config[field.key] ?? ""}
                          onChange={(v) =>
                            updateAction(i, {
                              ...action,
                              config: { ...action.config, [field.key]: v },
                            })
                          }
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
              {!personal && (
                <button
                  type="button"
                  onClick={() => {
                    const first = availableActions[0];
                    if (first)
                      patch({ actions: [...state.actions, blankAction(first, personal)] });
                  }}
                  className="text-xs font-medium text-primary hover:underline"
                >
                  + Add action
                </button>
              )}
            </div>
          </Step>
        </ol>

        {error && <p className="text-[13px] text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!isValid || saving}
            onClick={() => onSubmit(toRuleInput(state, catalog))}
          >
            {saving ? "Saving…" : initial ? "Save changes" : "Create rule"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Step({
  index,
  label,
  last,
  children,
}: {
  index: number;
  label: string;
  last?: boolean;
  children: React.ReactNode;
}) {
  return (
    <li className="relative flex gap-3 pb-5">
      {!last && (
        <span className="absolute bottom-0 left-3 top-7 w-px bg-border" aria-hidden />
      )}
      <span className="z-10 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground">
        {index}
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </div>
        <div className="mt-2">{children}</div>
      </div>
    </li>
  );
}

function FieldInput({
  field,
  personal,
  triggerFields,
  value,
  onChange,
}: {
  field: CatalogField;
  personal: boolean;
  triggerFields: string[];
  value: string;
  onChange: (value: string) => void;
}) {
  const placeholder = field.placeholder ?? undefined;
  let control: React.ReactNode;

  if (field.kind === "select") {
    const options =
      field.key === "target" && field.options
        ? targetOptionsFor(field.options, personal)
        : (field.options ?? []);
    control = (
      <Select value={value} onChange={(e) => onChange(e.target.value)} className="h-9">
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </Select>
    );
  } else if (field.kind === "textarea" || field.kind === "string_list" || field.kind === "keyvalue") {
    control = (
      <textarea
        className={TEXTAREA_CLASS}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={
          field.kind === "string_list"
            ? (placeholder ?? "one per line")
            : field.kind === "keyvalue"
              ? "Header-Name: value (one per line)"
              : placeholder
        }
      />
    );
  } else {
    control = (
      <Input
        type={field.kind === "number" ? "number" : "text"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-9"
      />
    );
  }

  return (
    <div className="space-y-1">
      <Label className={cn("text-xs", !field.required && "text-muted-foreground")}>
        {field.label}
        {!field.required && <span className="ml-1 font-normal">(optional)</span>}
      </Label>
      {control}
      {field.templateable && triggerFields.length > 0 && (
        <p className="text-[11px] text-muted-foreground">
          Insert: {triggerFields.map((f) => `{${f}}`).join(" ")}
        </p>
      )}
    </div>
  );
}

function IconButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
    >
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <path d="M18 6 6 18M6 6l12 12" />
      </svg>
    </button>
  );
}
