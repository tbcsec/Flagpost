"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useRulesSettings,
  useUpdateRulesSettings,
} from "@/lib/hooks/use-rules";
import { richTextToPlain } from "@/lib/rich-text";
import type { RichTextDoc, RulesSettings } from "@/lib/types";
import { toast } from "@/stores/toast";

// Admin → Site settings: the site-wide rules / code of conduct (#57). Applies
// to every competition without its own override; editing this text does NOT
// reset existing acceptances (owner decision, v1 — only an override change
// does, warned about on the competition's own settings page).
export function RulesSettingsPanel() {
  const settings = useRulesSettings();

  if (settings.isLoading || !settings.data) {
    return <Skeleton className="h-40 w-full" />;
  }
  return <PanelForm initial={settings.data} />;
}

function PanelForm({ initial }: { initial: RulesSettings }) {
  const t = useTranslations("admin.rules");
  const update = useUpdateRulesSettings();
  const [doc, setDoc] = useState<RichTextDoc>(initial.rules_text ?? {});
  const [displayOnly, setDisplayOnly] = useState(initial.rules_display_only);

  function onSave() {
    update.mutate(
      {
        // A visually-empty doc means "no rules configured" — no gate anywhere.
        rules_text: richTextToPlain(doc).trim() ? doc : null,
        rules_display_only: displayOnly,
      },
      {
        onSuccess: () => toast(t("rulesSaved"), { variant: "success" }),
        onError: (err) =>
          toast(t("couldntSave"), {
            description: (err as Error).message,
            variant: "destructive",
          }),
      },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <RichTextEditor value={doc} onChange={setDoc} />
        <label className="flex items-start gap-2.5 text-sm">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 rounded border-border"
            style={{ accentColor: "hsl(var(--primary))" }}
            checked={displayOnly}
            onChange={(e) => setDisplayOnly(e.target.checked)}
          />
          <span>
            {t("displayOnly")}
            <span className="ml-1 text-xs text-muted-foreground">
              {t("displayOnlyHint")}
            </span>
          </span>
        </label>
        <Button
          type="button"
          className="w-fit"
          onClick={onSave}
          disabled={update.isPending}
        >
          {update.isPending ? t("saving") : t("saveRules")}
        </Button>
      </CardContent>
    </Card>
  );
}
