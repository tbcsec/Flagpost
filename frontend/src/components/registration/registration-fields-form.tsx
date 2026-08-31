"use client";

// The shared renderer for custom registration fields (#350): turns a
// competition's field definitions into a controlled form. Reused everywhere a
// subject fills them — individual join, team creation, and the later edit
// surfaces — so the input rendering and required-marking live in one place.
// Field labels are organiser-authored content (not i18n'd, ADR-0029).

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import type { RegistrationField, RegistrationValues } from "@/lib/types";

/** True if any required field is unanswered — the caller disables submit. */
export function missingRequired(
  fields: RegistrationField[],
  values: RegistrationValues,
): boolean {
  return fields.some((f) => {
    if (!f.required) return false;
    const v = values[f.key];
    if (f.field_type === "checkbox") return v !== true;
    return v === undefined || v === null || String(v).trim() === "";
  });
}

export function RegistrationFieldsForm({
  fields,
  values,
  onChange,
  idPrefix = "rf",
}: {
  fields: RegistrationField[];
  values: RegistrationValues;
  onChange: (next: RegistrationValues) => void;
  idPrefix?: string;
}) {
  if (fields.length === 0) return null;
  const set = (key: string, value: string | boolean) =>
    onChange({ ...values, [key]: value });

  return (
    <div className="grid gap-4">
      {fields.map((field) => {
        const id = `${idPrefix}-${field.key}`;
        const value = values[field.key];
        const mark = field.required ? (
          <span className="text-destructive"> *</span>
        ) : null;

        if (field.field_type === "checkbox") {
          return (
            <label
              key={field.key}
              htmlFor={id}
              className="flex items-center gap-2 text-sm"
            >
              <input
                id={id}
                type="checkbox"
                checked={value === true}
                onChange={(e) => set(field.key, e.target.checked)}
              />
              <span>
                {field.label}
                {mark}
              </span>
            </label>
          );
        }

        return (
          <div key={field.key} className="grid gap-2">
            <Label htmlFor={id}>
              {field.label}
              {mark}
            </Label>
            {field.field_type === "select" ? (
              <Select
                id={id}
                value={typeof value === "string" ? value : ""}
                onChange={(e) => set(field.key, e.target.value)}
              >
                <option value="">—</option>
                {field.options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </Select>
            ) : field.field_type === "textarea" ? (
              <textarea
                id={id}
                value={typeof value === "string" ? value : ""}
                onChange={(e) => set(field.key, e.target.value)}
                rows={3}
                className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              />
            ) : (
              <Input
                id={id}
                value={typeof value === "string" ? value : ""}
                onChange={(e) => set(field.key, e.target.value)}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
