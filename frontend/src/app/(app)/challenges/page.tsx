"use client";

import { useState } from "react";

import { ChallengeAdmin } from "@/components/challenges/challenge-admin";
import { SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { useCategories } from "@/lib/hooks/use-categories";
import { useChallenges } from "@/lib/hooks/use-challenges";
import { useSubmitFlag } from "@/lib/hooks/use-submissions";
import { richTextToPlain } from "@/lib/rich-text";
import type { Challenge } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function ChallengesPage() {
  const { competitionId, data: competition } = useActiveCompetition();
  const challenges = useChallenges(competitionId ?? "");
  const categories = useCategories(competitionId ?? "");

  const [filter, setFilter] = useState<string>("all");
  const [open, setOpen] = useState<Challenge | null>(null);
  const [managing, setManaging] = useState(false);

  if (!competitionId) {
    return <p className="text-sm text-muted-foreground">No competition selected.</p>;
  }

  const categoryName = (id: string | null) =>
    categories.data?.find((c) => c.id === id)?.name ?? "uncategorized";

  const visible = (challenges.data ?? []).filter(
    (c) => filter === "all" || c.category_id === filter,
  );
  const solvedCount = (challenges.data ?? []).filter((c) => c.solved).length;

  const chips = [
    { id: "all", label: "All" },
    ...(categories.data ?? []).map((c) => ({ id: c.id, label: c.name })),
  ];

  return (
    <>
      <SectionHeader
        title="Challenges"
        subtitle={`${competition?.name ?? ""} · ${solvedCount} of ${challenges.data?.length ?? 0} solved`}
        actions={
          <Button variant={managing ? "secondary" : "default"} onClick={() => setManaging((m) => !m)}>
            {managing ? "Done managing" : "Manage challenges"}
          </Button>
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
          </button>
        ))}
      </div>

      {challenges.isLoading && (
        <p className="text-sm text-muted-foreground">Loading challenges…</p>
      )}
      {challenges.isError && (
        <p className="text-sm text-destructive">{(challenges.error as Error).message}</p>
      )}

      {challenges.data && (
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
                  <Badge variant={ch.solved ? "success" : "muted"}>
                    {ch.solved ? "Solved" : "Open"}
                  </Badge>
                </div>
              </div>
              <div className="text-base font-semibold">{ch.title}</div>
              <div className="flex items-baseline justify-between">
                <span className="font-mono text-sm font-semibold text-primary">{ch.points} pts</span>
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
}: {
  competitionId: string;
  challenge: Challenge;
  categoryName: string;
}) {
  const [flag, setFlag] = useState("");
  const submit = useSubmitFlag(competitionId, challenge.id);
  const result = submit.data;
  const alreadySolved = challenge.solved || result?.already_solved;

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    submit.mutate(flag, { onSuccess: () => setFlag("") });
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{challenge.title}</DialogTitle>
        <DialogDescription>
          {categoryName} · {challenge.points} pts · {challenge.solve_count} solves
        </DialogDescription>
      </DialogHeader>
      <p className="whitespace-pre-line text-sm leading-relaxed text-foreground">
        {richTextToPlain(challenge.description) || "No description."}
      </p>

      {alreadySolved ? (
        <p className="text-sm text-success">You&apos;ve solved this challenge.</p>
      ) : (
        <form className="grid gap-3" onSubmit={onSubmit}>
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
          {result && !result.correct && (
            <span className="text-sm text-destructive">Incorrect flag.</span>
          )}
          {result?.correct && (
            <span className="text-sm text-success">
              Correct — +{result.points_awarded}
              {result.is_first_blood ? " · first blood!" : ""}
            </span>
          )}
          {submit.isError && (
            <span className="text-sm text-destructive">{(submit.error as Error).message}</span>
          )}
          <DialogFooter>
            <Button type="submit" disabled={submit.isPending}>
              {submit.isPending ? "Submitting…" : "Submit flag"}
            </Button>
          </DialogFooter>
        </form>
      )}
    </>
  );
}
