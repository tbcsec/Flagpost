"use client";

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

const GUIDANCE_LABELS: Record<AiGuidanceLevel, string> = {
  platform_only: "Platform only — no challenge-solving help",
  conceptual: "Conceptual — general background topics, nothing specific",
  guided: "Guided — approaches and nudges, never full solutions",
};

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
  const update = useUpdateCompetitionAiSettings(competitionId);
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
        onSuccess: () => toast("Assistant settings saved", { variant: "success" }),
        onError: (err) =>
          toast("Couldn't save", {
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
          <CardTitle>Competitor assistant</CardTitle>
          <CardDescription>
            An AI chat competitors can open while the competition is running. It
            is read-only, structurally unable to see flags or unpublished
            challenges, and every conversation is reviewable by staff who hold
            the transcript permission. Requires the site-wide AI module to be
            configured and enabled.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="ai-comp-enabled">Availability</Label>
            <Select
              id="ai-comp-enabled"
              value={enabled ? "on" : "off"}
              onChange={(e) => setEnabled(e.target.value === "on")}
              className="max-w-md"
            >
              <option value="off">Off — competitors get no assistant</option>
              <option value="on">On — available while the competition runs</option>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="ai-comp-guidance">Guidance level</Label>
            <Select
              id="ai-comp-guidance"
              value={guidance}
              onChange={(e) => setGuidance(e.target.value)}
              className="max-w-md"
            >
              <option value="">
                Inherit site default ({GUIDANCE_LABELS[data.effective_guidance_level] ??
                  data.effective_guidance_level})
              </option>
              {(Object.keys(GUIDANCE_LABELS) as AiGuidanceLevel[]).map((level) => (
                <option key={level} value={level}>
                  {GUIDANCE_LABELS[level]}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">
              Controls how the assistant behaves. It shapes the model&apos;s
              instructions and is best-effort — it is not a data guarantee, and
              transcripts are how you verify it&apos;s being followed.
            </p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="ai-comp-meta">Challenge details</Label>
            <Select
              id="ai-comp-meta"
              value={metadata ? "on" : "off"}
              onChange={(e) => setMetadata(e.target.value === "on")}
              className="max-w-md"
            >
              <option value="off">
                Hidden — the assistant can&apos;t read any challenge
              </option>
              <option value="on">
                Visible — public challenge info only (never flags)
              </option>
            </Select>
            <p className="text-xs text-muted-foreground">
              A hard switch on what the assistant can <em>see</em>, separate from
              the guidance level: when hidden, the challenge-reading tools
              don&apos;t exist for the model at all.
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="flex items-center gap-3">
        <Button type="submit" className="w-fit" disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save changes"}
        </Button>
        {data.updated_at && (
          <span className="text-xs text-muted-foreground">
            Last saved {new Date(data.updated_at).toLocaleString()}
          </span>
        )}
      </div>
    </form>
  );
}
