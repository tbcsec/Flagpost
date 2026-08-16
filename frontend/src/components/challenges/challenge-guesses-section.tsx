"use client";

import { useTranslations } from "next-intl";
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
  const t = useTranslations("challenges.admin.guesses");
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
        toast(t("resetToast"), { variant: "success" });
        setTarget("");
      },
      onError: (e) => toast(t("resetError"), { description: (e as Error).message, variant: "destructive" }),
    });
  }

  async function resetEveryone() {
    if (
      !(await confirm({
        title: t("resetEveryoneConfirmTitle"),
        description: t("resetEveryoneConfirmDescription"),
        confirmLabel: t("resetEveryoneConfirmLabel"),
        destructive: false,
      }))
    ) {
      return;
    }
    reset.mutate({}, {
      onSuccess: () => toast(t("resetEveryoneToast"), { variant: "success" }),
      onError: (e) => toast(t("resetError"), { description: (e as Error).message, variant: "destructive" }),
    });
  }

  return (
    <section className="space-y-3 rounded-lg border border-border p-4">
      <div>
        <h4 className="text-sm font-semibold">{t("title")}</h4>
        <p className="text-xs text-muted-foreground">
          {t("description")}
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[16rem] flex-1">
          <EntityCombobox
            options={options}
            value={target}
            onChange={setTarget}
            placeholder={teamMode ? t("selectTeam") : t("selectCompetitor")}
          />
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={resetTarget}
          disabled={!target || reset.isPending}
        >
          {t("resetSelected")}
        </Button>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={resetEveryone}
        disabled={reset.isPending}
      >
        {t("resetEveryone")}
      </Button>
    </section>
  );
}
