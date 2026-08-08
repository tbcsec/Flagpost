import type { Challenge } from "@/lib/types";
import { cn } from "@/lib/utils";

/** A challenge's point worth, shared by the card grid and the list view.
 *
 *  When the multiple-choice wrong-guess penalty (#148) has docked the value for
 *  the requesting subject, `subject_value` is shown as the live worth and the
 *  base `value` is struck through beside it — so a competitor sees both what the
 *  question was worth and what it's worth to them now. With no penalty active it
 *  falls back to the plain value. Dynamic challenges keep their "dynamic" badge. */
export function ChallengeValue({
  challenge,
  className,
}: {
  challenge: Challenge;
  className?: string;
}) {
  const reduced = challenge.subject_value;
  const worth = reduced ?? challenge.value;
  return (
    <span className={cn("font-mono font-semibold text-primary", className)}>
      {reduced != null && (
        <span className="mr-1 font-normal text-muted-foreground line-through">
          {challenge.value}
        </span>
      )}
      {worth} pts
      {challenge.scoring_type === "dynamic" && (
        <span className="ml-1 text-[10px] font-normal text-muted-foreground">
          dynamic
        </span>
      )}
    </span>
  );
}
