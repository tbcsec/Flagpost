"use client";

import { CompetitionSettingsForm } from "@/components/competitions/competition-settings-form";
import { NoCompetition } from "@/components/app/no-competition";
import { ModulesPanel } from "@/components/competitions/modules-panel";
import { SectionHeader } from "@/components/app/section-header";
import { Card, CardContent } from "@/components/ui/card";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";

// Competition settings (ROADMAP #6) — fully wired via the update-competition
// hook, scoped to whichever competition is active in the topbar switcher. Also
// hosts per-competition module enable/disable (§11.3), which lives here (with the
// competition's other config) rather than the global Admin section.
export default function CompetitionSettingsPage() {
  const { competitionId, data, isLoading, isError, error } = useActiveCompetition();

  if (!competitionId) {
    return <NoCompetition />;
  }

  return (
    <>
      <SectionHeader title="Settings" subtitle={data?.name} />
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && <p className="text-sm text-destructive">{(error as Error).message}</p>}
      {data && (
        <div className="grid gap-8">
          <Card>
            <CardContent className="pt-6">
              <CompetitionSettingsForm competition={data} />
            </CardContent>
          </Card>

          <section className="grid gap-3">
            <div>
              <h2 className="text-lg font-semibold">Modules</h2>
              <p className="text-sm text-muted-foreground">
                Turn optional features on or off for this competition.
              </p>
            </div>
            <ModulesPanel competitionId={competitionId} />
          </section>
        </div>
      )}
    </>
  );
}
