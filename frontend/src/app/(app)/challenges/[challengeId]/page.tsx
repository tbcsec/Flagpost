"use client";

import { useParams } from "next/navigation";

import { NoCompetition } from "@/components/app/no-competition";
import { ProgrammingChallenge } from "@/components/challenges/programming-challenge";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";

// A programming challenge's own page (#449): the statement, examples and a code
// editor need the full width a dialog can't give, and contestants expect a
// problem to be deep-linkable. Flag challenges keep the board's dialog; the
// board links programming challenges here.
export default function ChallengePage() {
  const { challengeId } = useParams<{ challengeId: string }>();
  const { competitionId } = useActiveCompetition();
  if (!competitionId) return <NoCompetition />;
  return <ProgrammingChallenge competitionId={competitionId} challengeId={challengeId} />;
}
