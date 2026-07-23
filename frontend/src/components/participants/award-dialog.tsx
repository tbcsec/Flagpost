"use client";

import { useEffect, useMemo, useState } from "react";

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
import { useCreateAward } from "@/lib/hooks/use-participants";
import type { Participant } from "@/lib/types";
import { toast } from "@/stores/toast";

const TEXTAREA_CLASS =
  "flex min-h-16 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

// Judges (score_override) grant a titled, point-bearing award to one or more
// competitors from the roster. Points fold into the scoreboard immediately.
export function AwardDialog({
  competitionId,
  roster,
  open,
  onOpenChange,
}: {
  competitionId: string;
  roster: Participant[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const create = useCreateAward(competitionId);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [points, setPoints] = useState("0");
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (open) {
      setSelected(new Set());
      setTitle("");
      setDescription("");
      setPoints("0");
      setQuery("");
    }
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q
      ? roster.filter((p) => p.display_name.toLowerCase().includes(q))
      : roster;
  }, [roster, query]);

  function toggle(userId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (selected.size === 0 || !title.trim()) return;
    create.mutate(
      {
        user_ids: [...selected],
        title: title.trim(),
        description: description.trim() || undefined,
        points: Number(points) || 0,
      },
      {
        onSuccess: (awards) => {
          toast(
            `Awarded ${awards.length} competitor${awards.length === 1 ? "" : "s"}`,
            { variant: "success" },
          );
          onOpenChange(false);
        },
        onError: (err) =>
          toast("Couldn't create award", {
            description: (err as Error).message,
            variant: "destructive",
          }),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create award</DialogTitle>
          <DialogDescription>
            Grant a titled award and its points to selected competitors. Points
            are added to their score on the scoreboard.
          </DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={onSubmit}>
          <div className="grid gap-2">
            <Label htmlFor="award-title">Title</Label>
            <Input
              id="award-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Best write-up"
              maxLength={200}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="award-desc">Description (optional)</Label>
            <textarea
              id="award-desc"
              className={TEXTAREA_CLASS}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="award-points">Points</Label>
            <Input
              id="award-points"
              type="number"
              value={points}
              onChange={(e) => setPoints(e.target.value)}
              min={-10000}
              max={10000}
              className="w-32"
            />
            <p className="text-xs text-muted-foreground">
              0 for a badge with no scoring effect; negative to deduct.
            </p>
          </div>
          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label>Recipients</Label>
              <span className="text-xs text-muted-foreground">
                {selected.size} selected
              </span>
            </div>
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search competitors…"
            />
            <div className="max-h-52 overflow-y-auto rounded-md border border-border">
              {filtered.length === 0 ? (
                <p className="p-3 text-sm text-muted-foreground">No competitors match.</p>
              ) : (
                filtered.map((p) => (
                  <label
                    key={p.user_id}
                    className="flex cursor-pointer items-center gap-2.5 border-b border-border px-3 py-2 text-sm last:border-b-0 hover:bg-accent/40"
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-border"
                      style={{ accentColor: "hsl(var(--primary))" }}
                      checked={selected.has(p.user_id)}
                      onChange={() => toggle(p.user_id)}
                    />
                    <span className="flex-1">{p.display_name}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {p.points} pts
                    </span>
                  </label>
                ))
              )}
            </div>
          </div>
          {create.error && (
            <p className="text-sm text-destructive">{(create.error as Error).message}</p>
          )}
          <DialogFooter>
            <Button
              type="submit"
              disabled={create.isPending || selected.size === 0 || !title.trim()}
            >
              {create.isPending ? "Awarding…" : "Grant award"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
