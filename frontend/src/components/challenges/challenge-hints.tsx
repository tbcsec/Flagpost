"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { useHints, useRevealHint } from "@/lib/hooks/use-hints";
import { toast } from "@/stores/toast";

// Competitor-facing hint list on the challenge detail dialog (Phase 9). A hint's
// body stays hidden until this subject reveals it; revealing charges the cost
// once per subject (server-enforced) and the scoreboard updates live.
export function ChallengeHints({
  competitionId,
  challengeId,
}: {
  competitionId: string;
  challengeId: string;
}) {
  const t = useTranslations("challenges.hints");
  const hints = useHints(competitionId, challengeId);
  const reveal = useRevealHint(competitionId, challengeId);

  if (!hints.data || hints.data.length === 0) return null;

  return (
    <div className="grid gap-2 border-t border-border pt-4">
      <span className="text-[13px] font-semibold">{t("title")}</span>
      <ul className="grid gap-2">
        {hints.data.map((hint) => (
          <li
            key={hint.id}
            className="rounded-md border border-border px-3 py-2 text-sm"
          >
            {hint.revealed ? (
              <span className="text-muted-foreground">{hint.body}</span>
            ) : (
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">
                  {hint.cost > 0 ? t("cost", { cost: hint.cost }) : t("free")}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={reveal.isPending}
                  onClick={() =>
                    reveal.mutate(hint.id, {
                      onSuccess: (h) =>
                        toast(t("revealedToast"), {
                          description: h.cost > 0 ? t("revealedCost", { cost: h.cost }) : undefined,
                        }),
                    })
                  }
                >
                  {reveal.isPending ? t("revealing") : t("reveal")}
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {reveal.isError && (
        <p role="alert" className="text-sm text-destructive">{(reveal.error as Error).message}</p>
      )}
    </div>
  );
}
