"use client";

import { useState } from "react";

import { NoCompetition } from "@/components/app/no-competition";
import { SectionHeader } from "@/components/app/section-header";
import {
  CompetitionSettingsForm,
  type SettingsSection,
} from "@/components/competitions/competition-settings-form";
import { ModulesPanel } from "@/components/competitions/modules-panel";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";

type Tab = SettingsSection | "modules";

const TABS: { value: Tab; label: string }[] = [
  { value: "general", label: "General" },
  { value: "schedule", label: "Schedule" },
  { value: "scoring", label: "Scoring" },
  { value: "modules", label: "Modules" },
];

// Competition settings (ROADMAP #6), scoped to the active competition and split
// into tabs by category. The settings form stays mounted across the non-module
// tabs (kept hidden, not unmounted) so switching tabs never drops an unsaved edit;
// Modules (§11.3, per-competition feature toggles) is its own tab.
export default function CompetitionSettingsPage() {
  const { competitionId, data, isLoading, isError, error } = useActiveCompetition();
  const [tab, setTab] = useState<Tab>("general");

  if (!competitionId) {
    return <NoCompetition />;
  }

  return (
    <>
      <SectionHeader title="Settings" subtitle={data?.name} />
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && <p className="text-sm text-destructive">{(error as Error).message}</p>}
      {data && (
        <div className="grid gap-6">
          <Tabs tabs={TABS} value={tab} onValueChange={(v) => setTab(v as Tab)} />

          <div className={tab === "modules" ? "hidden" : ""}>
            <Card>
              <CardContent className="pt-6">
                <CompetitionSettingsForm
                  competition={data}
                  section={tab === "modules" ? "general" : tab}
                />
              </CardContent>
            </Card>
          </div>

          <div className={tab === "modules" ? "grid gap-3" : "hidden"}>
            <p className="text-sm text-muted-foreground">
              Turn optional features on or off for this competition.
            </p>
            <ModulesPanel competitionId={competitionId} />
          </div>
        </div>
      )}
    </>
  );
}
