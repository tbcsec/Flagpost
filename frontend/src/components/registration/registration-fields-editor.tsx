"use client";

// Organiser authoring for custom registration fields (#350): define the set of
// fields (label, key, type, required, and choices for a select) that competitors
// / teams fill when they enter. Replace-all save, like the managed vocab.

import { useState } from "react";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  useExportRegistrationValues,
  useRegistrationFields,
  usePutRegistrationFields,
} from "@/lib/hooks/use-registration-fields";
import type { RegistrationFieldInput, RegistrationFieldType } from "@/lib/types";
import { toast } from "@/stores/toast";

const TYPES: RegistrationFieldType[] = ["text", "textarea", "select", "checkbox"];

function slug(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

export function RegistrationFieldsEditor({
  competitionId,
}: {
  competitionId: string;
}) {
  const t = useTranslations("registration.editor");
  const { data } = useRegistrationFields(competitionId);
  const save = usePutRegistrationFields(competitionId);
  const exportCsv = useExportRegistrationValues(competitionId);
  const [draft, setDraft] = useState<RegistrationFieldInput[]>([]);

  // Seed the local draft from the server set once it arrives — adjust-during-
  // render (a setState in an effect trips react-hooks/set-state-in-effect).
  const [seeded, setSeeded] = useState(false);
  if (data && !seeded) {
    setSeeded(true);
    setDraft(
      data.map((f) => ({
        key: f.key,
        label: f.label,
        field_type: f.field_type,
        options: f.options,
        required: f.required,
        position: f.position,
      })),
    );
  }

  const update = (i: number, patch: Partial<RegistrationFieldInput>) =>
    setDraft((d) => d.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  const remove = (i: number) => setDraft((d) => d.filter((_, idx) => idx !== i));
  const add = () =>
    setDraft((d) => [
      ...d,
      { key: "", label: "", field_type: "text", options: [], required: false, position: d.length },
    ]);
  const move = (i: number, dir: -1 | 1) =>
    setDraft((d) => {
      const j = i + dir;
      if (j < 0 || j >= d.length) return d;
      const next = [...d];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });

  function onSave() {
    // Fill a missing key from the label; stamp order from position in the list.
    const fields = draft.map((f, i) => ({
      ...f,
      key: f.key.trim() || slug(f.label),
      position: i,
    }));
    save.mutate(fields, {
      onSuccess: () => toast(t("saved"), { variant: "success" }),
      onError: (e) =>
        toast(t("error"), {
          description: (e as Error).message,
          variant: "destructive",
        }),
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {draft.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("empty")}</p>
        )}
        {draft.map((field, i) => (
          <div
            key={i}
            className="grid gap-3 rounded-md border border-border p-3 sm:grid-cols-2"
          >
            <div className="grid gap-2">
              <Label htmlFor={`rf-label-${i}`}>{t("label")}</Label>
              <Input
                id={`rf-label-${i}`}
                value={field.label}
                onChange={(e) => update(i, { label: e.target.value })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor={`rf-type-${i}`}>{t("type")}</Label>
              <Select
                id={`rf-type-${i}`}
                value={field.field_type}
                onChange={(e) =>
                  update(i, { field_type: e.target.value as RegistrationFieldType })
                }
              >
                {TYPES.map((type) => (
                  <option key={type} value={type}>
                    {t(`types.${type}`)}
                  </option>
                ))}
              </Select>
            </div>
            {field.field_type === "select" && (
              <div className="grid gap-2 sm:col-span-2">
                <Label htmlFor={`rf-opts-${i}`}>{t("options")}</Label>
                <Input
                  id={`rf-opts-${i}`}
                  value={field.options.join(", ")}
                  placeholder={t("optionsPlaceholder")}
                  onChange={(e) =>
                    update(i, {
                      options: e.target.value
                        .split(",")
                        .map((o) => o.trim())
                        .filter(Boolean),
                    })
                  }
                />
              </div>
            )}
            <div className="flex items-center justify-between gap-2 sm:col-span-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={field.required}
                  onChange={(e) => update(i, { required: e.target.checked })}
                />
                {t("required")}
              </label>
              <div className="flex items-center gap-1">
                <Button size="sm" variant="ghost" onClick={() => move(i, -1)} disabled={i === 0}>
                  {t("up")}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => move(i, 1)} disabled={i === draft.length - 1}>
                  {t("down")}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => remove(i)}>
                  {t("remove")}
                </Button>
              </div>
            </div>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={add}>
            {t("add")}
          </Button>
          <Button onClick={onSave} disabled={save.isPending}>
            {save.isPending ? t("saving") : t("save")}
          </Button>
          <Button
            variant="ghost"
            className="ml-auto"
            onClick={() => exportCsv.mutate()}
            disabled={exportCsv.isPending}
          >
            {t("export")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
