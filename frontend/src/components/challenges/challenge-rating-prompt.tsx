"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useSubmitRating } from "@/lib/hooks/use-feedback";
import { useEnabledModules } from "@/lib/hooks/use-modules";
import type { Challenge } from "@/lib/types";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast";

// Post-solve 1–5 rating prompt (Phase 9, feedback module). Shown only when the
// competition has ratings enabled *and* the feedback module is on. Solvers can
// rate once and change it later; the stars fill to the current/hovered value.
export function ChallengeRatingPrompt({
  competitionId,
  challenge,
}: {
  competitionId: string;
  challenge: Challenge;
}) {
  const t = useTranslations("challenges.rating");
  const { data: competition } = useActiveCompetition();
  const enabledModules = useEnabledModules(competitionId);
  const submit = useSubmitRating(competitionId, challenge.id);
  const [hover, setHover] = useState(0);
  const [justRated, setJustRated] = useState<number | null>(null);

  const active =
    competition?.challenge_ratings_enabled &&
    (enabledModules.data ?? []).includes("feedback");
  if (!active) return null;

  const current = justRated ?? challenge.my_rating ?? 0;

  function rate(n: number) {
    submit.mutate(n, {
      onSuccess: () => setJustRated(n),
      onError: (e) =>
        toast(t("error"), { description: (e as Error).message, variant: "destructive" }),
    });
  }

  return (
    <div className="flex flex-col items-center gap-1">
      <span className="text-xs text-muted-foreground">{t("prompt")}</span>
      <div className="flex gap-0.5" onMouseLeave={() => setHover(0)}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            aria-label={t("star", { n })}
            onMouseEnter={() => setHover(n)}
            onClick={() => rate(n)}
            disabled={submit.isPending}
            className={cn(
              "text-2xl leading-none transition-colors",
              (hover || current) >= n ? "text-primary" : "text-muted-foreground/40",
            )}
          >
            ★
          </button>
        ))}
      </div>
      {justRated != null && <span className="text-xs text-success">{t("thanks")}</span>}
    </div>
  );
}
