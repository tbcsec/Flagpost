"use client";

import { SectionHeader } from "@/components/app/section-header";
import { ParticipantsPanel } from "@/components/participants/participants-panel";
import { TeamPanel } from "@/components/teams/team-panel";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";

// Participants. TEAM mode → create/join/leave a team and browse teams (TeamPanel).
// INDIVIDUAL mode → the per-user roster with standing (ParticipantsPanel), off
// the /participants endpoint. Both surfaces are fully wired.
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
        <ParticipantsPanel competitionId={competitionId} />
      )}
    </>
  );
}
