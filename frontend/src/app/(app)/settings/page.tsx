"use client";

import { CompetitionSettingsForm } from "@/components/competitions/competition-settings-form";
import { SectionHeader } from "@/components/app/section-header";
import { Card, CardContent } from "@/components/ui/card";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";

// Competition settings (ROADMAP #6) — fully wired via the update-competition
// hook, scoped to whichever competition is active in the topbar switcher.
export default function CompetitionSettingsPage() {
  const { competitionId, data, isLoading, isError, error } = useActiveCompetition();

  if (!competitionId) {
    return <p className="text-sm text-muted-foreground">No competition selected.</p>;
  }

  return (
    <>
      <SectionHeader title="Settings" subtitle={data?.name} />
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && <p className="text-sm text-destructive">{(error as Error).message}</p>}
      {data && (
        <Card>
          <CardContent className="pt-6">
            <CompetitionSettingsForm competition={data} />
          </CardContent>
        </Card>
      )}
    </>
  );
}
