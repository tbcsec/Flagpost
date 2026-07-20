"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { TeamPanel } from "@/components/teams/team-panel";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";

// Participants. In TEAM mode this is fully wired — create/join/leave a team and
// browse registered teams all go through the real teams endpoints. In
// INDIVIDUAL mode there's no participant-directory endpoint yet, and the staff
// "full roster" view is also unbuilt, so those are flagged rather than faked.
export default function ParticipantsPage() {
  const { competitionId, data: competition } = useActiveCompetition();
  const isTeam = competition?.participation_mode !== "individual";

  if (!competitionId) {
    return <p className="text-sm text-muted-foreground">No competition selected.</p>;
  }

  return (
    <>
      <SectionHeader
        title="Participants"
        subtitle={`${competition?.name ?? ""} · ${isTeam ? "teams" : "individual mode"}`}
      />

      {isTeam ? (
        <TeamPanel competitionId={competitionId} />
      ) : (
        <>
          <NotWiredNote>
            Individual-mode participant listing has no endpoint yet (teams are the
            only participation surface currently wired).
          </NotWiredNote>
          <Card>
            <CardHeader>
              <CardTitle>Participants</CardTitle>
              <CardDescription>Individual mode — no teams in this competition</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                A per-competition participant roster arrives with scoring (Phase 6).
              </p>
            </CardContent>
          </Card>
        </>
      )}
    </>
  );
}
