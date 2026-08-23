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
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCompetitionAiSettings,
  useUpdateCompetitionAiSettings,
} from "@/lib/hooks/use-ai";
import type { AiCompetitionSettings, AiGuidanceLevel } from "@/lib/types";
import { toast } from "@/stores/toast";

// Per-competition competitor-assistant controls (#98, ADR-0023 Phase 3), a card
// under Settings → Assistant, gated on edit_competition server-side. The copy
// keeps the spec's two controls honestly distinct: the guidance level shapes how
// the assistant *behaves* (best-effort), while challenge-metadata access decides
// what it can *see* (hard, code-enforced) — never conflated (spec §5).

export function AiCompetitionPanel({ competitionId }: { competitionId: string }) {
  const { data, isLoading } = useCompetitionAiSettings(competitionId);
  if (isLoading || !data) return <Skeleton className="h-48 w-full" />;
  // Remount on save so the form reseeds from the canonical server row.
  return (
    <AiCompetitionForm
      key={data.updated_at ?? "initial"}
      competitionId={competitionId}
      data={data}
    />
  );
}

function AiCompetitionForm({
  competitionId,
  data,
}: {
  competitionId: string;
  data: AiCompetitionSettings;
}) {
  const t = useTranslations("ai.competitionPanel");
  const update = useUpdateCompetitionAiSettings(competitionId);
  const GUIDANCE_LABELS: Record<AiGuidanceLevel, string> = {
    platform_only: t("guidancePlatformOnly"),
    conceptual: t("guidanceConceptual"),
    guided: t("guidanceGuided"),
  };
  const [enabled, setEnabled] = useState(data.competitor_enabled);
  // "" in the select means "inherit the site default".
  const [guidance, setGuidance] = useState<string>(data.guidance_level ?? "");
  const [metadata, setMetadata] = useState(data.challenge_metadata_access);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    update.mutate(
      {
        competitor_enabled: enabled,
        guidance_level: guidance === "" ? null : (guidance as AiGuidanceLevel),
        challenge_metadata_access: metadata,
      },
      {
        onSuccess: () => toast(t("savedToast"), { variant: "success" }),
        onError: (err) =>
          toast(t("saveFailed"), {
            description: (err as Error).message,
            variant: "destructive",
          }),
      },
    );
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-5">
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="ai-comp-enabled">{t("availability")}</Label>
            <Select
              id="ai-comp-enabled"
              value={enabled ? "on" : "off"}
              onChange={(e) => setEnabled(e.target.value === "on")}
              className="max-w-md"
            >
              <option value="off">{t("availOff")}</option>
              <option value="on">{t("availOn")}</option>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="ai-comp-guidance">{t("guidanceLevel")}</Label>
            <Select
              id="ai-comp-guidance"
              value={guidance}
              onChange={(e) => setGuidance(e.target.value)}
              className="max-w-md"
            >
              <option value="">
                {t("inheritDefault", {
                  label:
                    GUIDANCE_LABELS[data.effective_guidance_level] ??
                    data.effective_guidance_level,
                })}
              </option>
              {(Object.keys(GUIDANCE_LABELS) as AiGuidanceLevel[]).map((level) => (
                <option key={level} value={level}>
                  {GUIDANCE_LABELS[level]}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">{t("guidanceHint")}</p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="ai-comp-meta">{t("challengeDetails")}</Label>
            <Select
              id="ai-comp-meta"
              value={metadata ? "on" : "off"}
              onChange={(e) => setMetadata(e.target.value === "on")}
              className="max-w-md"
            >
              <option value="off">{t("metaHidden")}</option>
              <option value="on">{t("metaVisible")}</option>
            </Select>
            <p className="text-xs text-muted-foreground">
              {t.rich("metaHint", { em: (chunks) => <em>{chunks}</em> })}
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button type="submit" className="w-fit" disabled={update.isPending}>
          {update.isPending ? t("saving") : t("save")}
        </Button>
        {data.updated_at && (
          <span className="text-xs text-muted-foreground">
            {t("lastSaved", { date: new Date(data.updated_at).toLocaleString() })}
          </span>
        )}
      </div>
    </form>
  );
}
