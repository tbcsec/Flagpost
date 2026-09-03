"use client";

// Demo login-accounts editor (#360). A controlled list the AppearancePanel
// renders only on a demo instance. Each row becomes a click-to-sign-in button
// on the login card; the referenced accounts must actually exist (they ride the
// baseline alongside these entries). Passwords are throwaway demo credentials —
// shown in plain text because the card fills them.

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { DemoCredential } from "@/lib/types";

const MAX_DEMO_CREDENTIALS = 12;

const EMPTY: DemoCredential = {
  label: "",
  description: "",
  identifier: "",
  password: "",
};

export function DemoCredentialsEditor({
  value,
  onChange,
}: {
  value: DemoCredential[];
  onChange: (next: DemoCredential[]) => void;
}) {
  const t = useTranslations("admin.appearance.demoCredentials");

  const patch = (index: number, fields: Partial<DemoCredential>) =>
    onChange(value.map((c, i) => (i === index ? { ...c, ...fields } : c)));
  const remove = (index: number) =>
    onChange(value.filter((_, i) => i !== index));
  const add = () => onChange([...value, { ...EMPTY }]);

  return (
    <div className="grid gap-3">
      {value.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      )}
      {value.map((account, index) => (
        // Index key: rows carry no stable id and are only added/removed, not
        // reordered.
        <div
          key={index}
          className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-2"
        >
          <div className="grid gap-1">
            <Label htmlFor={`demo-cred-label-${index}`}>{t("accountLabel")}</Label>
            <Input
              id={`demo-cred-label-${index}`}
              value={account.label}
              maxLength={60}
              onChange={(e) => patch(index, { label: e.target.value })}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor={`demo-cred-identifier-${index}`}>
              {t("identifier")}
            </Label>
            <Input
              id={`demo-cred-identifier-${index}`}
              value={account.identifier}
              maxLength={254}
              onChange={(e) => patch(index, { identifier: e.target.value })}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor={`demo-cred-password-${index}`}>{t("password")}</Label>
            <Input
              id={`demo-cred-password-${index}`}
              value={account.password}
              maxLength={128}
              onChange={(e) => patch(index, { password: e.target.value })}
            />
          </div>
          <div className="grid gap-1">
            <Label htmlFor={`demo-cred-description-${index}`}>
              {t("descriptionField")}
            </Label>
            <Input
              id={`demo-cred-description-${index}`}
              value={account.description}
              maxLength={120}
              onChange={(e) => patch(index, { description: e.target.value })}
            />
          </div>
          <div className="flex justify-end sm:col-span-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => remove(index)}
            >
              {t("remove")}
            </Button>
          </div>
        </div>
      ))}
      {value.length < MAX_DEMO_CREDENTIALS && (
        <div>
          <Button type="button" variant="outline" size="sm" onClick={add}>
            {t("add")}
          </Button>
        </div>
      )}
    </div>
  );
}
