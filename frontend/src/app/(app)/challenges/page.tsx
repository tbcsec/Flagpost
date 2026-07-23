"use client";

import { useState } from "react";

import { ChallengeAdmin } from "@/components/challenges/challenge-admin";
import { NoCompetition } from "@/components/app/no-competition";
import { ChallengeHints } from "@/components/challenges/challenge-hints";
import { CollabNote } from "@/components/collab/collab-note";
import { PresenceIndicator } from "@/components/presence/presence-indicator";
import { SectionHeader } from "@/components/app/section-header";
import { FlagpostMark } from "@/components/brand/flagpost-mark";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, FlagEmptyIcon } from "@/components/ui/empty-state";
import { SkeletonCards } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useMyTeam } from "@/lib/hooks/use-teams";
import { usePresence } from "@/lib/hooks/use-presence";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useCategories } from "@/lib/hooks/use-categories";
import { ChallengeRatingPrompt } from "@/components/challenges/challenge-rating-prompt";
import { useChallenges, useChallengeSolves } from "@/lib/hooks/use-challenges";
import { useSubmitFlag } from "@/lib/hooks/use-submissions";
import { relativeTime } from "@/lib/datetime";
import { richTextToPlain } from "@/lib/rich-text";
import type { Challenge } from "@/lib/types";
import { toast } from "@/stores/toast";
import { cn } from "@/lib/utils";

export default function ChallengesPage() {
  const { competitionId, data: competition } = useActiveCompetition();
  const access = useAccess();
  const challenges = useChallenges(competitionId ?? "");
  const categories = useCategories(competitionId ?? "");

  const [filter, setFilter] = useState<string>("all");
  const [open, setOpen] = useState<Challenge | null>(null);
  const [managing, setManaging] = useState(false);

  if (!competitionId) {
    return <NoCompetition />;
  }

  const categoryName = (id: string | null) =>
    categories.data?.find((c) => c.id === id)?.name ?? "uncategorized";

  const allData = challenges.data ?? [];
  const visible = allData.filter(
    (c) => filter === "all" || c.category_id === filter,
  );
  const solvedCount = allData.filter((c) => c.solved).length;

  // Each chip carries its solved/total progress so competitors can see at a
  // glance where they stand per category.
  const chips = [
    { id: "all", label: "All", solved: solvedCount, total: allData.length },
    ...(categories.data ?? []).map((c) => {
      const inCat = allData.filter((x) => x.category_id === c.id);
      return {
        id: c.id,
        label: c.name,
        solved: inCat.filter((x) => x.solved).length,
        total: inCat.length,
      };
    }),
  ];

  return (
    <>
      <SectionHeader
        title="Challenges"
        subtitle={`${competition?.name ?? ""} · ${solvedCount} of ${challenges.data?.length ?? 0} solved`}
        actions={
          access.canManageActiveCompetition ? (
            <Button variant={managing ? "secondary" : "default"} onClick={() => setManaging((m) => !m)}>
              {managing ? "Done managing" : "Manage challenges"}
            </Button>
          ) : undefined
        }
      />

      <div className="flex flex-wrap gap-2">
        {chips.map((chip) => (
          <button
            key={chip.id}
            onClick={() => setFilter(chip.id)}
            className={cn(
              "rounded-full border px-3.5 py-1.5 text-sm font-medium capitalize transition-colors",
              filter === chip.id
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-foreground hover:bg-accent/60",
            )}
          >
            {chip.label}
            <span className="ml-1.5 font-mono text-xs opacity-70">
              {chip.solved}/{chip.total}
            </span>
          </button>
        ))}
      </div>

      {challenges.isLoading && <SkeletonCards count={6} />}
      {challenges.isError && (
        <p className="text-sm text-destructive">{(challenges.error as Error).message}</p>
      )}

      {challenges.data && allData.length === 0 && (
        <EmptyState
          icon={<FlagEmptyIcon />}
          title="No challenges yet"
          description={
            access.canManageActiveCompetition
              ? "Add your first challenge to open the competition — save it as a draft and publish when it's ready."
              : "The organisers haven't published any challenges yet. Check back once the competition opens."
          }
          action={
            access.canManageActiveCompetition && !managing ? (
              <Button onClick={() => setManaging(true)}>Create a challenge</Button>
            ) : undefined
          }
        />
      )}

      {challenges.data && allData.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((ch) => (
            <button
              key={ch.id}
              onClick={() => setOpen(ch)}
              className={cn(
                "grid gap-2.5 rounded-lg border bg-card p-5 text-left shadow-sm transition-colors hover:border-primary/40",
                ch.solved ? "border-success/45" : "border-border",
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="text-[11px] font-semibold capitalize tracking-wide text-muted-foreground">
                  {categoryName(ch.category_id)}
                </span>
                <div className="flex gap-1.5">
                  {ch.state === "draft" && <Badge variant="outline">Draft</Badge>}
                  {ch.locked ? (
                    <Badge variant="outline">🔒 Locked</Badge>
                  ) : (
                    <Badge variant={ch.solved ? "success" : "muted"}>
                      {ch.solved ? "Solved" : "Open"}
                    </Badge>
                  )}
                </div>
              </div>
              <div className="text-base font-semibold">{ch.title}</div>
              <div className="flex items-baseline justify-between">
                <span className="font-mono text-sm font-semibold text-primary">
                  {ch.value} pts
                  {ch.scoring_type === "dynamic" && (
                    <span className="ml-1 text-[10px] font-normal text-muted-foreground">dynamic</span>
                  )}
                </span>
                <span className="text-xs text-muted-foreground">{ch.solve_count} solves</span>
              </div>
            </button>
          ))}
          {visible.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No challenges in this category yet.
            </p>
          )}
        </div>
      )}

      {managing && (
        <div className="mt-2 border-t border-border pt-6">
          <ChallengeAdmin competitionId={competitionId} />
        </div>
      )}

      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent>
          {open && (
            <ChallengeDialogBody
              competitionId={competitionId}
              challenge={open}
              categoryName={categoryName(open.category_id)}
              allChallenges={challenges.data ?? []}
            />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

function ChallengeDialogBody({
  competitionId,
  challenge,
  categoryName,
  allChallenges,
}: {
  competitionId: string;
  challenge: Challenge;
  categoryName: string;
  allChallenges: Challenge[];
}) {
  const [flag, setFlag] = useState("");
  const submit = useSubmitFlag(competitionId, challenge.id);
  // Titles of the prerequisites still blocking this challenge (unlock chain).
  const lockedBy = challenge.locked
    ? challenge.prerequisites
        .map((id) => allChallenges.find((c) => c.id === id))
        .filter((c): c is Challenge => Boolean(c) && !c!.solved)
        .map((c) => c.title)
    : [];
  // Live "who else is on this challenge" while the detail dialog is open (§4.1).
  const presence = usePresence("challenge", challenge.id);
  // The team's private scratchpad for this challenge (§4.2) — only when the
  // viewer is actually on a team (team-mode competitions); scoped to that team.
  const myTeam = useMyTeam(competitionId);
  const result = submit.data;
  const justSolved = result?.correct === true;
  const alreadySolved = challenge.solved || result?.already_solved;
  const isMultipleChoice = challenge.flag_type === "multiple_choice";
  // Guesses left: the latest submit result wins, else the value the list carried.
  const remaining = result?.attempts_remaining ?? challenge.attempts_remaining;
  const outOfGuesses =
    isMultipleChoice && remaining === 0 && !justSolved && !alreadySolved;

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    submit.mutate(flag, {
      onSuccess: (r) => {
        setFlag("");
        if (r.correct) {
          toast(
            r.is_first_blood ? "First blood!" : "Solved!",
            { description: `${challenge.title} · +${r.points_awarded} pts`, variant: "success" },
          );
        }
      },
    });
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{challenge.title}</DialogTitle>
        <DialogDescription>
          {categoryName} · {challenge.value} pts
          {challenge.scoring_type === "dynamic" && " (dynamic)"} · {challenge.solve_count} solves
        </DialogDescription>
      </DialogHeader>
      {presence.others.length > 0 && (
        <PresenceIndicator
          members={presence.others}
          label={`${presence.others.length} other${presence.others.length === 1 ? "" : "s"} viewing`}
        />
      )}
      <p className="whitespace-pre-line text-sm leading-relaxed text-foreground">
        {richTextToPlain(challenge.description) || "No description."}
      </p>

      {challenge.locked ? (
        <div className="grid gap-2 rounded-lg border border-border bg-muted/40 p-6 text-center">
          <div className="text-2xl">🔒</div>
          <div className="text-sm font-medium">Locked</div>
          <p className="text-xs text-muted-foreground">
            {lockedBy.length > 0
              ? `Solve ${lockedBy.join(", ")} to unlock this challenge.`
              : "Solve this challenge's prerequisites to unlock it."}
          </p>
        </div>
      ) : justSolved ? (
        <div className="flex flex-col items-center gap-2 rounded-lg border border-success/40 bg-success/10 p-6 text-center">
          <FlagpostMark size={40} theme="dark" />
          <div className="text-base font-semibold text-success">
            {result.is_first_blood ? "First blood!" : "Solved!"}
          </div>
          <div className="font-mono text-sm text-muted-foreground">
            +{result.points_awarded} pts
          </div>
          <ChallengeRatingPrompt competitionId={competitionId} challenge={challenge} />
        </div>
      ) : alreadySolved ? (
        <div className="grid gap-3">
          <p className="text-sm text-success">You&apos;ve solved this challenge.</p>
          <ChallengeRatingPrompt competitionId={competitionId} challenge={challenge} />
        </div>
      ) : outOfGuesses ? (
        <p className="text-sm text-destructive">
          You&apos;ve used all your guesses for this question.
        </p>
      ) : (
        <form className="grid gap-3" onSubmit={onSubmit}>
          {isMultipleChoice ? (
            <div className="grid gap-2">
              <Label>Choose an answer</Label>
              <div className="grid gap-1.5">
                {(challenge.choices ?? []).map((option) => (
                  <label
                    key={option}
                    className="flex items-center gap-2.5 rounded-md border border-border px-3 py-2 text-sm hover:bg-accent/40"
                  >
                    <input
                      type="radio"
                      name="mc-answer"
                      checked={flag === option}
                      onChange={() => setFlag(option)}
                      style={{ accentColor: "hsl(var(--primary))" }}
                    />
                    <span>{option}</span>
                  </label>
                ))}
              </div>
              {typeof remaining === "number" && (
                <span className="text-xs text-muted-foreground">
                  {remaining} guess{remaining === 1 ? "" : "es"} remaining.
                </span>
              )}
            </div>
          ) : (
            <div className="grid gap-2">
              <Label htmlFor="flag-submit">Flag</Label>
              <Input
                id="flag-submit"
                value={flag}
                onChange={(e) => setFlag(e.target.value)}
                placeholder="flag{...}"
                className="font-mono"
                autoComplete="off"
                required
              />
            </div>
          )}
          {result && !result.correct && (
            <span className="text-sm text-destructive">
              {isMultipleChoice ? "Incorrect answer." : "Incorrect flag."}
            </span>
          )}
          {submit.isError && (
            <span className="text-sm text-destructive">{(submit.error as Error).message}</span>
          )}
          <DialogFooter>
            <Button type="submit" disabled={submit.isPending || (isMultipleChoice && !flag)}>
              {submit.isPending
                ? "Submitting…"
                : isMultipleChoice
                  ? "Submit answer"
                  : "Submit flag"}
            </Button>
          </DialogFooter>
        </form>
      )}

      <ChallengeHints competitionId={competitionId} challengeId={challenge.id} />

      <ChallengeSolves competitionId={competitionId} challengeId={challenge.id} />

      {myTeam.data && (
        <section className="grid gap-2">
          <div>
            <h3 className="text-sm font-medium">Team notes</h3>
            <p className="text-xs text-muted-foreground">
              A shared scratchpad for {myTeam.data.name} — visible only to your team, live as you type.
            </p>
          </div>
          <CollabNote docKey={`team_challenge:${myTeam.data.id}:${challenge.id}`} />
        </section>
      )}
    </>
  );
}

// "Who solved this" — earliest first, the first tagged as first blood (🩸).
function ChallengeSolves({
  competitionId,
  challengeId,
}: {
  competitionId: string;
  challengeId: string;
}) {
  const { data: solvers } = useChallengeSolves(competitionId, challengeId);
  if (!solvers || solvers.length === 0) {
    return (
      <section className="grid gap-1">
        <h3 className="text-sm font-medium">Solves</h3>
        <p className="text-xs text-muted-foreground">
          No solves yet — be the first to draw blood.
        </p>
      </section>
    );
  }
  return (
    <section className="grid gap-2">
      <h3 className="text-sm font-medium">
        Solves <span className="text-muted-foreground">({solvers.length})</span>
      </h3>
      <ul className="grid max-h-48 gap-1 overflow-y-auto">
        {solvers.map((s) => (
          <li
            key={s.subject_id}
            className="flex items-center justify-between gap-2 text-sm"
          >
            <span className="flex items-center gap-1.5">
              {s.is_first_blood && <span title="First blood">🩸</span>}
              <span className={cn(s.is_first_blood && "font-medium")}>{s.name}</span>
            </span>
            <span className="text-xs text-muted-foreground">
              {relativeTime(s.solved_at)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
