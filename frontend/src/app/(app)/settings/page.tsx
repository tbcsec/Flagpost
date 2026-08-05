"use client";

import { useState } from "react";

import { AiCompetitionPanel } from "@/components/ai/ai-competition-panel";
import { NoCompetition } from "@/components/app/no-competition";
import { SectionHeader } from "@/components/app/section-header";
import { CategoryManager } from "@/components/challenges/challenge-admin";
import {
  CompetitionSettingsForm,
  type SettingsSection,
} from "@/components/competitions/competition-settings-form";
import { ModulesPanel } from "@/components/competitions/modules-panel";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useEnabledModules } from "@/lib/hooks/use-modules";

type Tab = SettingsSection | "modules" | "assistant";

const TABS: { value: Tab; label: string }[] = [
  { value: "general", label: "General" },
  { value: "schedule", label: "Schedule" },
  { value: "challenges", label: "Challenges" },
  { value: "rules", label: "Rules" },
  { value: "assistant", label: "Assistant" },
  { value: "modules", label: "Modules" },
];

// Competition settings (ROADMAP #6), scoped to the active competition and split
// into tabs by category. The settings form stays mounted across the non-module
// tabs (kept hidden, not unmounted) so switching tabs never drops an unsaved edit;
// Modules (§11.3, per-competition feature toggles) is its own tab.
export default function CompetitionSettingsPage() {
  const { competitionId, data, isLoading, isError, error } = useActiveCompetition();
  const [tab, setTab] = useState<Tab>("general");
  // The Assistant tab only exists while the ai module is enabled here — with it
  // off, nothing on the tab would work (§11.3, same treatment as the nav).
  const enabledModules = useEnabledModules(competitionId ?? "", Boolean(competitionId));
  const aiEnabled = !enabledModules.data || enabledModules.data.includes("ai");
  const visibleTabs = TABS.filter((t) => t.value !== "assistant" || aiEnabled);
  const activeTab: Tab = tab === "assistant" && !aiEnabled ? "general" : tab;

  if (!competitionId) {
    return <NoCompetition />;
  }

  // The settings form hosts the general/schedule/challenges/rules sections;
  // assistant + modules are their own panels (own endpoints).
  const isFormTab = activeTab !== "modules" && activeTab !== "assistant";

  return (
    <>
      <SectionHeader title="Settings" subtitle={data?.name} />
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && <p role="alert" className="text-sm text-destructive">{(error as Error).message}</p>}
      {data && (
        <div className="grid gap-6">
          <Tabs tabs={visibleTabs} value={activeTab} onValueChange={(v) => setTab(v as Tab)} />

          <div className={isFormTab ? "" : "hidden"}>
            <Card>
              <CardContent className="pt-6">
                <CompetitionSettingsForm
                  competition={data}
                  section={isFormTab ? (activeTab as SettingsSection) : "general"}
                />
              </CardContent>
            </Card>
          </div>

          {/* Categories live in their own card (own CRUD endpoints) under the
              Challenges tab, alongside the tag/difficulty vocab for uniformity. */}
          <div className={activeTab === "challenges" ? "" : "hidden"}>
            <CategoryManager competitionId={competitionId} />
          </div>

          {/* Mounted only when shown (unlike the form) — it has no cross-tab
              unsaved state to preserve, and its queries then run on demand. */}
          {activeTab === "assistant" && (
            <AiCompetitionPanel competitionId={competitionId} />
          )}

          <div className={activeTab === "modules" ? "grid gap-3" : "hidden"}>
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
