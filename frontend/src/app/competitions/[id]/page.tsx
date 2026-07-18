"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { CompetitionSettingsForm } from "@/components/competitions/competition-settings-form";
import { TeamPanel } from "@/components/teams/team-panel";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useCompetition } from "@/lib/hooks/use-competitions";
import { useAuthStore } from "@/stores/auth";

export default function CompetitionDetailPage() {
  const params = useParams<{ id: string }>();
  const status = useAuthStore((s) => s.status);
  const { data, isLoading, isError, error } = useCompetition(params.id);

  if (status === "anonymous") {
    return (
      <main className="mx-auto max-w-2xl p-8">
        <p className="text-sm text-muted-foreground">
          Please{" "}
          <Link href="/login" className="text-primary hover:underline">
            sign in
          </Link>{" "}
          to view this competition.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-8">
      <Button asChild variant="ghost" size="sm">
        <Link href="/">← Competitions</Link>
      </Button>

      {isLoading && (
        <p className="text-sm text-muted-foreground">Loading competition…</p>
      )}
      {isError && (
        <p className="text-sm text-destructive">{(error as Error).message}</p>
      )}
      {data && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>{data.name}</CardTitle>
              <CardDescription>
                Competition settings — {data.participation_mode} ·{" "}
                {data.visibility}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <CompetitionSettingsForm competition={data} />
            </CardContent>
          </Card>

          {/* Team-vs-individual is per-competition config (§11.3): the team
              surface only exists in team mode. */}
          {data.participation_mode === "team" && (
            <TeamPanel competitionId={data.id} />
          )}
        </>
      )}
    </main>
  );
}
