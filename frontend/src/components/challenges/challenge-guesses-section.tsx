"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { EntityCombobox } from "@/components/ui/entity-combobox";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useResetGuesses } from "@/lib/hooks/use-challenges";
import { useParticipants } from "@/lib/hooks/use-participants";
import { useTeams } from "@/lib/hooks/use-teams";
import { toast } from "@/stores/toast";

// Staff control for the multiple-choice guess cap: reset a subject's guesses (or
// everyone's) non-destructively. Team-mode picks a team; individual-mode a
// competitor. Only rendered for multiple_choice challenges (edit mode).
export function ChallengeGuessesSection({
  competitionId,
  challengeId,
}: {
  competitionId: string;
  challengeId: string;
}) {
  const { data: competition } = useActiveCompetition();
  const teamMode = competition?.participation_mode === "team";
  const reset = useResetGuesses(competitionId, challengeId);
  const confirm = useConfirm();

  const teams = useTeams(competitionId);
  const participants = useParticipants(competitionId, !teamMode);
  const options = teamMode
    ? (teams.data ?? []).map((t) => ({ value: t.id, label: t.name }))
    : (participants.data ?? []).map((p) => ({ value: p.user_id, label: p.display_name }));

  const [target, setTarget] = useState("");

  function resetTarget() {
    if (!target) return;
    reset.mutate(teamMode ? { team_id: target } : { user_id: target }, {
      onSuccess: () => {
        toast("Guesses reset", { variant: "success" });
        setTarget("");
      },
      onError: (e) => toast("Couldn't reset", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  async function resetEveryone() {
    if (
      !(await confirm({
        title: "Reset guesses for everyone?",
        description:
          "Every competitor gets a fresh set of guesses on this challenge. Their submission history is kept.",
        confirmLabel: "Reset for everyone",
        destructive: false,
      }))
    ) {
      return;
    }
    reset.mutate({}, {
      onSuccess: () => toast("Guesses reset for everyone", { variant: "success" }),
      onError: (e) => toast("Couldn't reset", { description: (e as Error).message, variant: "destructive" }),
    });
  }

  return (
    <section className="space-y-3 rounded-lg border border-border p-4">
      <div>
        <h4 className="text-sm font-semibold">Guesses</h4>
        <p className="text-xs text-muted-foreground">
          Multiple-choice guesses are capped competition-wide. Reset them to grant a
          fresh set — history is kept.
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[16rem] flex-1">
          <EntityCombobox
            options={options}
            value={target}
            onChange={setTarget}
            placeholder={teamMode ? "Select a team…" : "Select a competitor…"}
          />
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={resetTarget}
          disabled={!target || reset.isPending}
        >
          Reset for selected
        </Button>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={resetEveryone}
        disabled={reset.isPending}
      >
        Reset for everyone
      </Button>
    </section>
  );
}
